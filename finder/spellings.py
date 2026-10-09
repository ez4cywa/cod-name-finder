"""Recover a bounded set of CSV display spellings, accepting only source hashes.

Export paths can use separators where an audio encoding tail originally had
periods. Shape recognition proposes strings; the declared source-table profile
is the only authority that can accept one. This module does no file I/O and
creates neither evidence records nor exclusion keys.
"""
from __future__ import annotations

import re
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

from .hashing import PROFILES, parse_hash
from .registry import table_rule

MAX_NAME_BYTES = 1024
_SEP = r"[./\\]"
_MODERN_TAIL = re.compile(
    r"(?P<stem>.+)" + _SEP + r"(?P<codec>[A-Za-z]{1,4}[0-9]*)"
    + _SEP + r"(?P<quality>[0-9]+)" + _SEP + r"(?P<rate>[0-9]+)"
    + _SEP + r"(?P<language>[A-Za-z_]+)"
)
_LEGACY_TAIL = re.compile(
    r"(?P<stem>.+)" + _SEP + r"(?P<codec>[A-Za-z]{2}[0-9]+)"
    + _SEP + r"(?P<platform>[pP][cC])"
    + r"(?:" + _SEP + r"(?P<language>[A-Za-z_]+))?"
    + _SEP + r"(?P<extension>[sS][nN][dD])"
)


@lru_cache(maxsize=64)
def _source_profiles(declared, legacy):
    """Old CSV rows can preserve case or carry an earlier 60-bit source key.

    These temporary readers never modify registered target profiles. Newer
    resource tables and complete 64-bit alias tables do not use this exception.
    """
    profiles = list(declared)
    if legacy:
        profiles.extend(replace(profile, ascii_lower=False) for profile in declared)
        profiles.extend(replace(profile, mask=profile.mask & ((1 << 60) - 1))
                        for profile in tuple(profiles))
    return tuple(dict.fromkeys(profiles))


def _split_encoding(name):
    """Return literal stem and period-delimited tail for two precise audio shapes."""
    match = _MODERN_TAIL.fullmatch(name)
    if match:
        fields = [match[name] for name in ('codec', 'quality', 'rate', 'language')]
        return match['stem'], '.' + '.'.join(fields)
    match = _LEGACY_TAIL.fullmatch(name)
    if match:
        fields = [match['codec'], match['platform']]
        if match['language'] is not None:
            fields.append(match['language'])
        fields.append(match['extension'])
        return match['stem'], '.' + '.'.join(fields)
    return None


def _candidates(display, sound):
    """Yield (spelling, requires_literal_path_profile), without combinatorial edits."""
    names = [display]
    if sound:
        encoding = _split_encoding(display)
        if encoding:
            stem, tail = encoding
            names.append(stem + tail)
        # Some exports turn the complete original period-delimited path into a
        # directory tree. A full source hash must prove this particular proposal.
        names.append(display.replace('\\', '.').replace('/', '.'))
    seen = set()
    for name in names:
        if name not in seen:
            seen.add(name)
            yield name, False
    if sound:
        for name in names:
            encoding = _split_encoding(name)
            if encoding:
                stem, tail = encoding
                literal = stem.replace('/', '\\') + tail
            else:
                literal = name.replace('/', '\\')
            if literal not in seen:
                seen.add(literal)
                yield literal, True


def resolve_table_spelling(table_or_path, key, display) -> str | None:
    """Return a source-verified spelling, or None when no bounded variant verifies.

    Key equality uses the complete source-table mask, including historical
    60-bit/case-preserving variants of old non-v2 FNV63 tables. A 64-bit
    alias key therefore cannot be accepted through a matching low 63 bits.
    Original case and spelling take precedence when their full source hash
    already agrees. Audio-only edits never apply to other table domains.
    """
    if not isinstance(display, str) or not display or any(c in display for c in '\0\r\n'):
        return None
    try:
        if len(display.encode('utf-8')) > MAX_NAME_BYTES:
            return None
        if isinstance(key, bool):
            return None
        if isinstance(key, str):
            key = parse_hash(key)
        if not isinstance(key, int) or not 0 <= key < 1 << 64:
            return None
        rule = table_rule(table_or_path)
    except (TypeError, ValueError, UnicodeError):
        return None
    if not rule or not rule.get('profile'):
        return None
    declared = tuple(PROFILES[pid] for pid in dict.fromkeys(
        [rule['profile'], *rule.get('alternate_profiles', [])]) if pid in PROFILES)
    legacy = rule['profile'] == 'fnv1a63' and not Path(table_or_path).stem.lower().endswith('_v2')
    profiles = _source_profiles(declared, legacy)
    for name, literal_paths_only in _candidates(display, rule.get('kind') == 'sndasset'):
        for profile in profiles:
            if literal_paths_only and profile.slash:
                continue
            if profile.digest(name) == key:
                return name
    return None
