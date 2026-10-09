"""Opt-in read-only community CSV acquisition and per-row provenance isolation.

No CSV tables ship in the application. HTTPS downloads are pinned to a repository
commit; caches are application data and synchronization never submits changes.
"""
from __future__ import annotations
import csv
from dataclasses import dataclass, asdict
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.request
from urllib.parse import urlparse
from .hashing import PROFILES, parse_hash
from .registry import table_rule
from .spellings import resolve_table_spelling

REPOSITORY = 'echo000/cod-name-db'
MAX_FILE_BYTES = 128 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
CSV_NAME = re.compile(r'^[A-Za-z0-9_-]+\.csv$')


@dataclass(frozen=True)
class CommunityRow:
    key: int | None
    name: str
    table: str
    kind: str
    profile: str | None
    status: str  # verified / quarantined / borrowed
    reason: str
    row: int

    def json(self):
        return asdict(self)


def _response(url):
    if urlparse(url).scheme != 'https' or urlparse(url).hostname not in ('api.github.com', 'raw.githubusercontent.com'):
        raise ValueError('Community synchronization requires the fixed GitHub HTTPS source')
    response = urllib.request.urlopen(urllib.request.Request(url, headers={
        'User-Agent': 'CODNameFinder-read-only-community-sync', 'Accept': 'application/vnd.github+json'}), timeout=45)
    if urlparse(response.url).scheme != 'https' or urlparse(response.url).hostname not in ('api.github.com', 'raw.githubusercontent.com'):
        response.close()
        raise ValueError('Unexpected community download redirect')
    return response


def _json_url(url):
    with _response(url) as response:
        data = response.read(4 * 1024 * 1024 + 1)
    if len(data) > 4 * 1024 * 1024:
        raise ValueError('Community metadata exceeds limit')
    return json.loads(data)


def sync_community(cache_dir, enabled=False, refresh=False, tables=None):
    """Return {enabled,csv_dir,commit,source,files}; disabled means zero I/O/network.

    A complete cached snapshot is reused without a network request until refresh
    is explicit. git/Python/.NET installations are unnecessary on a new PC.
    Failed downloads never publish ``current.json`` and do not mutate old copies.
    """
    if not enabled:
        return {'enabled': False, 'csv_dir': None, 'commit': None, 'source': REPOSITORY, 'files': []}
    cache = Path(cache_dir).resolve()
    current = cache / 'current.json'
    if current.is_file() and not refresh:
        metadata = json.loads(current.read_text(encoding='utf-8'))
        commit = metadata.get('commit', '')
        if not re.fullmatch(r'[0-9a-f]{40}', commit):
            raise ValueError('Invalid cached community commit')
        folder = cache / 'snapshots' / commit / 'csv'
        # Confirm content hashes, not fresh local modification timestamps.
        for item in metadata['files']:
            if not CSV_NAME.fullmatch(item['name']):
                raise ValueError('Invalid cached table path')
            path = folder / item['name']
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
                raise ValueError('Community cache changed; use explicit refresh: ' + item['name'])
        return {**metadata, 'enabled': True, 'csv_dir': str(folder), 'cached': True}
    head = _json_url(f'https://api.github.com/repos/{REPOSITORY}/commits/HEAD')
    commit = head['sha']
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('Invalid upstream commit')
    listing = _json_url(f'https://api.github.com/repos/{REPOSITORY}/contents/csv?ref={commit}')
    wanted = set(tables) if tables else None
    files = sorted(item['name'] for item in listing if item.get('type') == 'file' and
                   CSV_NAME.fullmatch(item.get('name', '')) and (wanted is None or item['name'] in wanted))
    if not files or wanted is not None and set(files) != wanted:
        raise ValueError('Requested community tables are missing')
    folder = cache / 'snapshots' / commit / 'csv'
    folder.mkdir(parents=True, exist_ok=True)
    copied, total = [], 0
    for name in files:
        temporary = folder / (name + '.download')
        digest, size = hashlib.sha256(), 0
        try:
            with _response(f'https://raw.githubusercontent.com/{REPOSITORY}/{commit}/csv/{name}') as response, temporary.open('wb') as output:
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    total += len(chunk)
                    if size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
                        raise ValueError('Community download exceeds configured size limit')
                    output.write(chunk)
                    digest.update(chunk)
            os.replace(temporary, folder / name)
        finally:
            if temporary.exists():
                temporary.unlink()
        copied.append({'name': name, 'bytes': size, 'sha256': digest.hexdigest()})
    metadata = {'enabled': True, 'source': REPOSITORY, 'commit': commit, 'files': copied,
                'license': 'No upstream LICENSE; local read-only use, no bundled full tables or automatic submission'}
    temporary = cache / 'current.json.download'
    temporary.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, current)
    return {**metadata, 'csv_dir': str(folder), 'cached': False}


def iter_csv_rows(path):
    """Yield structural CSV rows without trusting their names or stored keys."""
    path = Path(path)
    with path.open(encoding='utf-8-sig', newline='') as stream:
        for index, columns in enumerate(csv.reader(stream), 1):
            if not columns:
                continue
            name = columns[1] if len(columns) >= 2 else ''
            try:
                if len(columns) != 2 or not name or len(name) > 16384 or any(c in name for c in '\0\r\n'):
                    raise ValueError('invalid-name-or-column-count')
                key = parse_hash(columns[0])
                yield index, key, name, ''
            except ValueError as error:
                yield index, None, name, str(error)


def iter_community(csv_dir, selected_profile=None, borrowed=False):
    """Stream CommunityRow; only status=verified may calibrate or exclude.

    Display spellings must recover to their source-table key before verification.
    Unknown tables and hash/name mismatches are quarantined. ``borrowed=True``
    forces candidate-only provenance even for mathematically valid source rows.
    selected_profile limits tables; it never relabels their hash algorithm.
    """
    if selected_profile and selected_profile not in PROFILES:
        raise ValueError('Unknown selected community profile: ' + selected_profile)
    folder = Path(csv_dir)
    if not folder.is_dir():
        raise ValueError('Community CSV directory does not exist')
    for path in sorted(folder.glob('*.csv')):
        rule = table_rule(path)
        expected = [rule['profile'], *rule.get('alternate_profiles', [])] if rule and rule['profile'] else []
        if selected_profile and selected_profile not in expected:
            continue
        kind = rule['kind'] if rule else 'unknown'
        for index, key, name, reason in iter_csv_rows(path):
            if reason:
                yield CommunityRow(key, name, path.stem, kind, None, 'quarantined', reason, index)
                continue
            if borrowed:
                yield CommunityRow(key, name, path.stem, kind, None, 'borrowed', 'candidate-only-cross-title', index)
                continue
            restored = resolve_table_spelling(path, key, name)
            matched = next((pid for pid in expected
                            if restored is not None and PROFILES[pid].digest(restored) == key), None)
            if matched:
                yield CommunityRow(key, restored, path.stem, kind, matched, 'verified', 'exact-table-profile-rehash', index)
            else:
                yield CommunityRow(key, name, path.stem, kind, None, 'quarantined',
                                   'name-hash-mismatch' if expected else 'unknown-table-domain', index)


def import_community(csv_dir, selected_profile=None, borrowed=False, output_dir=None):
    """Summarize streamed import, optionally persist three separate JSONL files.

    Returns counts and file paths, not a multi-million-row in-memory list.
    Consumers needing candidates/verified keys use ``iter_community`` directly.
    """
    import contextlib
    counts = dict(verified=0, quarantined=0, borrowed=0)
    tables = {}
    files = {}
    with contextlib.ExitStack() as stack:
        streams = {}
        if output_dir:
            destination = Path(output_dir)
            destination.mkdir(parents=True, exist_ok=True)
            for status in counts:
                path = destination / (status + '.jsonl')
                files[status] = str(path.resolve())
                streams[status] = stack.enter_context(path.open('w', encoding='utf-8'))
        for row in iter_community(csv_dir, selected_profile, borrowed):
            counts[row.status] += 1
            by_table = tables.setdefault(row.table, dict(verified=0, quarantined=0, borrowed=0))
            by_table[row.status] += 1
            if streams:
                streams[row.status].write(json.dumps(row.json(), ensure_ascii=False) + '\n')
    return {'source': str(Path(csv_dir).resolve()), 'selected_profile': selected_profile,
            'counts': counts, 'tables': tables, 'files': files, 'borrowed_candidate_only': borrowed}
