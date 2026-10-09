"""Finite sound-name hypotheses from observed paths and alias families.

This is an independent implementation of naming relationships, not upstream
search code. Inputs supplied by the pipeline have already been rehashed in
their own domains. Donor names remain candidates; only target sound names
teach directories, namespaces and encoding tails. This module never creates
evidence or decides that a candidate is a real asset name.

Two deliberately narrow grammars are used:

* A namespace is a complete directory component made of ASCII underscore
  words, also occurring as whole words in the filename stem. If nested
  components overlap, only the longest matching namespace is retained. Every
  occurrence is replaced together, preserving the donor's slash spelling.
  Replacement namespaces and their opaque first-period encoding tails are
  observed together in target sounds.
* A sound family is an underscore stem with at least three tokens, after
  removing an optional final numeric take (and optional ``_ads``). An alias
  family absent from target sounds borrows only the deepest shared prefix of
  at least three tokens. Its directory and exact take-plus-encoding tuple
  come from one target observation. Donors never make a target family present.

No numeric range, codec, sample rate, directory or title root is invented.
"""
import re
from collections import defaultdict
from dataclasses import dataclass

from .candidates import Plan


MAX_SOUND_CANDIDATES = 1_000_000
MAX_SOUND_PLANS = 128
MAX_NAME_BYTES = 1024
_WORDS = re.compile(r'[A-Za-z0-9]+(?:_[A-Za-z0-9]+)*\Z')
_TAKE = re.compile(r'(_[0-9]+(?:_ads)?)\Z', re.I)


class _Cancelled(Exception):
    pass


def _check(control):
    if control() != 'run':
        raise _Cancelled()


def _names(values, label, control):
    if isinstance(values, (str, bytes)):
        raise ValueError(label + '须为名称列表')
    try:
        iterator = iter(values)
    except TypeError as error:
        raise ValueError(label + '须为名称列表') from error
    names = set()
    for name in iterator:
        _check(control)
        if not isinstance(name, str) or not name.strip() or any(c in name for c in '\x00\r\n'):
            raise ValueError(label + '包含空名称、非字符串、NUL 或换行')
        try:
            length = len(name.encode('utf-8'))
        except UnicodeEncodeError as error:
            raise ValueError(label + '包含无法编码为 UTF-8 的名称') from error
        if length > MAX_NAME_BYTES:
            raise ValueError(label + '中的名称不得超过 1024 字节')
        names.add(name)
    return sorted(names)


@dataclass(frozen=True)
class _Sound:
    directory: str
    stem: str
    encoding: str
    family: str
    take: str


def _sound(name):
    # The first period begins an opaque tail: .qnn.85.48000.all stays intact.
    last = max(name.rfind('/'), name.rfind('\\'))
    directory, filename = name[:last + 1], name[last + 1:]
    stem, dot, tail = filename.partition('.')
    if not stem or not dot or not tail:
        return None
    match = _TAKE.search(stem)
    family, take = (stem[:match.start()], match.group()) if match else (stem, '')
    return _Sound(directory, stem, dot + tail, family, take)


def _tokens(family):
    return tuple(part.lower() for part in family.split('_')) if _WORDS.fullmatch(family) else ()


def _namespace_pattern(namespace):
    # Underscores are delimiters for whole words, but part of a multiword
    # namespace. ASCII case matching avoids expanding Unicode case folds.
    return re.compile(r'(?<![A-Za-z0-9])' + re.escape(namespace) + r'(?![A-Za-z0-9])', re.I | re.ASCII)


def _namespaces(sound):
    path = sound.directory + sound.stem
    choices = set()
    for component in re.split(r'[/\\]', sound.directory):
        if not _WORDS.fullmatch(component) or not any(c.isalpha() for c in component):
            continue
        pattern = _namespace_pattern(component)
        if pattern.search(sound.stem) and len(pattern.findall(path)) >= 2:
            choices.add(component)
    # ar_kilo2 is more informative than a nested kilo2 directory. Distinct,
    # nonoverlapping repeated identities remain separate finite hypotheses.
    return sorted(component for component in choices if not any(
        component.lower() != other.lower() and _namespace_pattern(component).search(other)
        for other in choices))


def _frame(sound, namespace):
    pattern = _namespace_pattern(namespace)
    path = sound.directory + sound.stem
    matches = list(pattern.finditer(path))
    prefix = path[:matches[0].start()]
    middles = tuple(path[a.end():b.start()] for a, b in zip(matches, matches[1:]))
    suffix = path[matches[-1].end():]
    return prefix, middles, suffix


def build_sound_plans(donor_names, target_sound_names, target_alias_names, *,
                      max_candidates=MAX_SOUND_CANDIDATES, max_plans=MAX_SOUND_PLANS,
                      control=lambda: 'run'):
    """Return deterministic ``[(Chinese label, Plan), ...]`` candidate plans.

    Limits are inclusive upper bounds, additionally capped by the module's
    one-million-candidate/128-plan safety bounds. Zero returns no plans.
    Cancellation at any preparation point returns no executable partial plans.
    Counts in metadata are pre-pruning upper bounds, not unique-name counts.
    """
    for value, label in ((max_candidates, '候选上限'), (max_plans, '计划上限')):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(label + '须为非负整数')
    candidate_limit = min(max_candidates, MAX_SOUND_CANDIDATES)
    plan_limit = min(max_plans, MAX_SOUND_PLANS)
    if not candidate_limit or not plan_limit:
        return []
    try:
        donors = _names(donor_names, '借用声音名称', control)
        targets = _names(target_sound_names, '当前声音名称', control)
        aliases = _names(target_alias_names, '当前声音别名', control)
        observed = [(name, sound) for name in targets if (sound := _sound(name)) is not None]
        if not observed:
            return []
        target_set = set(targets)
        namespaces = defaultdict(set)
        present = set()
        # An index by observed prefix makes deepest-family lookup independent
        # of donor contents and avoids scanning every sound for every alias.
        families = defaultdict(set)
        for _, sound in observed:
            _check(control)
            for namespace in _namespaces(sound):
                namespaces[namespace].add(sound.encoding)
            tokens = _tokens(sound.family)
            if len(tokens) >= 3:
                present.add(tokens)
                for depth in range(3, len(tokens) + 1):
                    families[tokens[:depth]].add((sound.directory, sound.take + sound.encoding))
        namespace_pairs = sorted((namespace, encoding) for namespace, tails in namespaces.items()
                                 for encoding in tails)
        frames = defaultdict(set)
        for name in donors:
            _check(control)
            sound = _sound(name)
            if sound is None:
                continue
            for namespace in _namespaces(sound):
                prefix, middles, suffix = _frame(sound, namespace)
                frames[prefix, middles, suffix].add(namespace.lower())

        # Keep the large alias x observation product as two short lists rather
        # than materializing it during preparation. Each emitted plan still
        # binds its directory and take/encoding to one exact observation.
        alias_groups = defaultdict(set)
        for alias in aliases:
            _check(control)
            # Aliases are domain names, not paths or encoded sound filenames.
            if '/' in alias or '\\' in alias or '.' in alias:
                continue
            match = _TAKE.search(alias)
            family = alias[:match.start()] if match else alias
            tokens = _tokens(family)
            if len(tokens) < 3 or tokens in present:
                continue
            for depth in range(len(tokens), 2, -1):
                observations = families.get(tokens[:depth])
                if observations:
                    alias_groups[tokens[:depth]].add(family)
                    break

        namespace_counts = defaultdict(int)
        for namespace, _ in namespace_pairs:
            namespace_counts[namespace.lower()] += 1
        def option_count(sources):
            # Several donor identities with the same frame produce the same
            # target names. Keep that frame once instead of charging repeatedly.
            return (len(namespace_pairs) - namespace_counts[next(iter(sources))]
                    if len(sources) == 1 else len(namespace_pairs))
        namespace_upper = sum(option_count(sources) for sources in frames.values())
        alias_upper = sum(len(values) * len(families[prefix]) for prefix, values in alias_groups.items())
        upper = namespace_upper + alias_upper
        plans = []
        emitted = 0

        def append(label, prefix, values, suffix, rule, upper_bound, *,
                   candidate_ceiling=candidate_limit, plan_ceiling=plan_limit, **details):
            nonlocal emitted
            _check(control)
            remaining = min(candidate_limit, candidate_ceiling) - emitted
            if remaining <= 0 or len(plans) >= min(plan_limit, plan_ceiling):
                return 0
            selected = []
            consumed = 0
            for consumed, value in enumerate(values, 1):
                _check(control)
                candidate = prefix + value + suffix
                if candidate in target_set or len(candidate.encode('utf-8')) > MAX_NAME_BYTES:
                    continue
                selected.append(value)
                if len(selected) == remaining:
                    break
            if not selected:
                return consumed
            plan = Plan([[prefix], selected, [suffix]])
            plan.metadata = {
                'generator': 'sound-observed-v1', 'rule': rule,
                'target_kinds': ['sndasset'], 'asset_type': 'sndasset',
                'source_names': len(donors), 'target_sound_names': len(targets),
                'target_alias_names': len(aliases), 'verification_required': 'complete-target-hash',
                'candidate_only': True, 'bounded_search': True,
                'max_candidates': candidate_limit, 'max_plans': plan_limit,
                'plan_combinations_upper_bound': upper_bound,
                'plan_limited': plan.total < upper_bound, **details,
            }
            plans.append((label, plan))
            emitted += plan.total
            return consumed

        # Alias absence is measured solely in the target corpus. It runs first,
        # but a large alias corpus must not consume every plan slot. Reserve at
        # most a quarter for observed namespace frames when both methods exist.
        # Tiny limits remain deterministic alias-first rather than promising
        # that two methods fit in one candidate or one plan.
        namespace_frames = sum(option_count(sources) > 0 for sources in frames.values())
        reserve_plans = min(plan_limit // 4, namespace_frames) if alias_upper else 0
        reserve_candidates = min(candidate_limit // 4, namespace_upper) if alias_upper else 0
        if not reserve_plans or not reserve_candidates:
            reserve_plans = reserve_candidates = 0

        def alias_work():
            for family_prefix, values in sorted(alias_groups.items()):
                ordered = sorted(values)
                for directory, take_encoding in sorted(families[family_prefix]):
                    yield directory, take_encoding, len(family_prefix), ordered

        alias_iterator = iter(alias_work())
        pending_alias = None

        def run_aliases(candidate_ceiling, plan_ceiling):
            nonlocal pending_alias
            while emitted < candidate_ceiling and len(plans) < plan_ceiling:
                _check(control)
                if pending_alias is None:
                    pending_alias = next(alias_iterator, None)
                if pending_alias is None:
                    return
                directory, take_encoding, depth, values = pending_alias
                consumed = append('声音别名缺失文件族', directory, values, take_encoding,
                    'alias-missing-family', len(values), candidate_ceiling=candidate_ceiling,
                    plan_ceiling=plan_ceiling, shared_prefix_tokens=depth,
                    tuple_binding='directory+take+encoding')
                pending_alias = ((directory, take_encoding, depth, values[consumed:])
                                 if consumed < len(values) else None)

        run_aliases(candidate_limit - reserve_candidates, plan_limit - reserve_plans)
        for (prefix, middles, suffix), sources in sorted(frames.items()):
            _check(control)
            if emitted == candidate_limit or len(plans) >= plan_limit:
                break
            def replacements():
                for namespace, encoding in namespace_pairs:
                    if len(sources) == 1 and namespace.lower() in sources:
                        continue
                    yield namespace + ''.join(middle + namespace for middle in middles) + suffix + encoding
            append('声音重复命名空间关联替换', prefix, replacements(), '',
                   'repeated-namespace', option_count(sources),
                   repeated_occurrences=len(middles) + 1,
                   tuple_binding='namespace+encoding')
        # A missing/short namespace method can leave its reservation unused.
        # Resume the same alias cursor, including an interrupted family's tail,
        # so transferred quota does not repeat already emitted candidates.
        run_aliases(candidate_limit, plan_limit)
        _check(control)
        method_candidates = defaultdict(int)
        method_plans = defaultdict(int)
        for _, plan in plans:
            method_candidates[plan.metadata['rule']] += plan.total
            method_plans[plan.metadata['rule']] += 1
        for _, plan in plans:
            plan.metadata.update(unbounded_sound_combinations_upper_bound=upper,
                emitted_sound_combinations=emitted,
                omitted_sound_combinations_upper_bound=max(0, upper - emitted),
                reserved_namespace_candidates=reserve_candidates,
                reserved_namespace_plans=reserve_plans,
                emitted_candidates_by_rule=dict(method_candidates),
                emitted_plans_by_rule=dict(method_plans))
        return plans
    except _Cancelled:
        return []
