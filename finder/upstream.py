"""Opt-in findings contributions, with a local preview and fresh upstream checks.

Only generated name lists and a whitelisted method summary leave this module.
The work database, export manifests, target census and credentials remain local.
No Git, GitHub CLI or original research checkout is required by the application.
"""
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import struct
import sys
import time
import uuid

from . import VERSION
from .contribution_evidence import collect_export
from .github_api import GitHubApi, GitHubError, UPSTREAM, COMMUNITY
from .github_credentials import get_token, save_token, delete_token, validate_token
from .hashing import PROFILES, parse_hash

MASK63 = (1 << 63) - 1
GAME_TAGS = {'BO4': 'BLKOPS04', 'BOCW': 'BLKOPSCW', 'MWII': 'MODWAR22',
             'MWIII': 'YAMYAMOK', 'BO6': 'BLACKOP6', 'BO7': 'BLACKOP7', 'COD2026': 'MODWAR7'}
KINDS = {'xanim': 'xanim', 'image': 'image', 'material': 'material',
         'sndasset': 'sound_asset', 'soundbankalias': 'sound_alias'}
MODERN_TABLES = frozenset('fnv1a_' + name + '_v2.csv' for name in
    ('ximages', 'xmaterials', 'xanims', 'xsounds', 'soundbanks_aliases', 'soundbanks', 'animpkgs'))
MAX_PACKAGE = 32 * 1024 * 1024


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _digest(value):
    return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()


def _write_json(path, value):
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _cache_root():
    root = Path(os.environ.get('LOCALAPPDATA') or Path.home()/'.cache')
    return root/'CODNameFinder'/'upstream-cache'


def authentication(action='auth-status', token=None):
    if action == 'auth-clear':
        delete_token()
        return {'authenticated': False, 'credential_saved': False, 'login': ''}
    saved = get_token()
    supplied = token or saved
    if not supplied:
        if action == 'auth-save':
            raise ValueError('请输入 GitHub Token 后再保存凭据')
        return {'authenticated': False, 'credential_saved': False, 'login': ''}
    api = GitHubApi(validate_token(supplied), _cache_root())
    user = api.request('GET', '/user')
    login = _login(user)
    if action == 'auth-save':
        save_token(supplied)
        saved = supplied
    return {'authenticated': True, 'credential_saved': saved is not None, 'login': login}


def _login(user):
    login = user.get('login', '')
    if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})', login):
        raise ValueError('GitHub 返回的用户名无效')
    return login


def _eligible(local):
    rows = []
    rejected = Counter(local.get('rejected', {}))
    game = GAME_TAGS.get(local['game'])
    for row in local['rows']:
        kind = KINDS.get(row['kind'])
        if not game or not kind:
            rejected['upstream_unsupported_game_or_type'] += 1
            continue
        # Rust validates ASCII case folding while the derived Python collector
        # uses Unicode lower(). Keep both rehash paths identical for posting.
        if not row['name'].isascii():
            rejected['upstream_non_ascii_name'] += 1
            continue
        if game in ('BLKOPS04', 'BLKOPSCW'):
            expected = PROFILES['fnv1a63']
            if game == 'BLKOPS04' and kind == 'sound_asset' and row['profile'] == 'fnv1a63-no-fold':
                expected = PROFILES['fnv1a63-no-fold']
        else:
            expected = PROFILES['fnv1a64' if kind == 'sound_alias' else 'iw-resource63']
        if row['profile'] != expected.id or expected.digest(row['name']) != parse_hash(row['hash']):
            rejected['upstream_incompatible_hash_domain'] += 1
            continue
        rows.append({**row, 'kind': kind})
    return game or local['game'], rows, rejected


def _snapshot_membership(data, census, game, rows):
    """Stream the pinned census; hold only keys actually proposed for upload."""
    if len(data) < 18 or data[:6] != b'CODIDS':
        raise ValueError('上游快照不是 CODIDS v1')
    version, length = struct.unpack_from('<HH', data, 6)
    if version != 1 or not 1 <= length <= 64 or len(data) < 18 + length:
        raise ValueError('上游快照头无效')
    if data[10:10+length].decode('ascii') != game:
        raise ValueError('上游快照与所选作品不一致')
    count, = struct.unpack_from('<Q', data, 10+length)
    if count > 10_000_000 or len(data) != 18+length+10*count:
        raise ValueError('上游快照记录长度不一致')
    text = census.decode('utf-8-sig')
    header = re.search(r'^' + re.escape(game) + r'\s*--\s*(\d+) assets in (\d+) filled pools\s*$', text, re.M)
    if not header or int(header[1]) != count:
        raise ValueError('上游池清单作品或总数不一致')
    pools = {}; labels = set()
    for line in text.splitlines():
        match = re.fullmatch(r'\s*(\d+)\s+([a-zA-Z0-9_]+)\s+(\d+)\s*', line)
        if not match:
            continue
        pool, label, size = int(match[1]), match[2], int(match[3])
        if pool > 65535 or pool in pools or label in labels:
            raise ValueError('上游池清单出现重复或无效类型')
        pools[pool] = (KINDS.get(label, label), size); labels.add(label)
    if len(pools) != int(header[2]) or sum(size for _, size in pools.values()) != count:
        raise ValueError('上游池清单计数不完整')
    wanted = {(row['kind'], parse_hash(row['hash']) & MASK63) for row in rows}
    found = set(); actual = Counter(); previous = None
    for key, pool in struct.iter_unpack('<QH', memoryview(data)[18+length:]):
        record = (key, pool)
        if key > MASK63 or previous is not None and record <= previous or pool not in pools:
            raise ValueError('上游快照排序、位宽或池号无效')
        previous = record; actual[pool] += 1
        item = (pools[pool][0], key)
        if item in wanted:
            found.add(item)
    if any(actual[pool] != size for pool, (_, size) in pools.items()):
        raise ValueError('上游快照与池清单逐池计数不符')
    return [row for row in rows if (row['kind'], parse_hash(row['hash']) & MASK63) in found]


def _name_form(name):
    # Conservative exclusion also covers source tables' display separators.
    # It never turns a display spelling into an uploaded or verified name.
    return name.strip().lower().replace('\\', '/').replace('.', '/')


class _Claims:
    def __init__(self, rows):
        self.keys = {value: set() for row in rows for value in
                     (parse_hash(row['hash']), parse_hash(row['hash']) & MASK63)}
        self.names = {_name_form(row['name']): set() for row in rows}
        self.invalid_rows = 0

    def add(self, raw, name, source):
        try:
            key = parse_hash(raw)
        except ValueError:
            self.invalid_rows += 1
        else:
            for value in (key, key & MASK63):
                if value in self.keys:
                    self.keys[value].add(source)
        if isinstance(name, str) and _name_form(name) in self.names:
            self.names[_name_form(name)].add(source)

    def text(self, data, source):
        for line in data.decode('utf-8-sig').splitlines():
            if not line.strip():
                continue
            raw, sep, name = line.partition(',')
            if not sep:
                self.invalid_rows += 1
                continue
            self.add(raw, name, source)

    def csv(self, data):
        try:
            for columns in csv.reader(io.StringIO(data.decode('utf-8-sig')), strict=True):
                if not columns:
                    continue
                if len(columns) != 2:
                    raise ValueError('社区 CSV 列数无效，无法完成投稿前排重')
                self.add(columns[0], columns[1], 'community')
        except csv.Error as error:
            raise ValueError('社区 CSV 无法完整解析，已保留本地结果') from error

    def source(self, row):
        sources = self.names.get(_name_form(row['name']), set())
        for key in (parse_hash(row['hash']), parse_hash(row['hash']) & MASK63):
            sources = sources | self.keys.get(key, set())
        return next((source for source in ('community', 'merged', 'open_pr') if source in sources), None)


def _open_signature(pulls):
    return sorted([int(pr['number']), pr['head']['sha']] for pr in pulls)


def _check_network(api, game, rows, progress):
    progress(0, '检查当前上游快照与资产类型…')
    upstream = api.tree(UPSTREAM)
    entries = {entry['path']: entry for entry in upstream['entries'] if entry.get('type') == 'blob'}
    paths = [f'snapshots/{game.lower()}.ids', f'snapshots/{game.lower()}.pools.txt']
    if not all(path in entries for path in paths):
        raise ValueError('上游没有此作品的完整快照与池清单，名称保留在本地')
    blobs = api.blobs(UPSTREAM, [entries[path] for path in paths])
    held = _snapshot_membership(*(blobs[entries[path]['sha']] for path in paths), game, rows)
    excluded = Counter(upstream_snapshot_missing=len(rows)-len(held))
    checked = {'upstream_commit': upstream['commit'], 'upstream_tree': upstream['tree_sha'],
               'community_commit': '', 'open_heads': [], 'submission_blobs': 0, 'invalid_existing_rows': 0}
    if not held:
        return held, excluded, checked
    claims = _Claims(held)
    progress(0, '刷新社区表并检查已发表名称…')
    community = api.tree(COMMUNITY)
    tables = [entry for entry in community['entries'] if entry.get('type') == 'blob'
              and re.fullmatch(r'csv/[A-Za-z0-9_-]+\.csv', entry['path'])]
    if game not in ('BLKOPS04', 'BLKOPSCW'):
        tables = [entry for entry in tables if entry['path'].split('/')[-1] in MODERN_TABLES]
        if {entry['path'].split('/')[-1] for entry in tables} != MODERN_TABLES:
            raise ValueError('现代作品的七张社区表不完整，停止投稿')
    if not tables:
        raise ValueError('社区表目录为空，停止投稿')
    table_blobs = api.blobs(COMMUNITY, tables)
    for entry in tables:
        claims.csv(table_blobs[entry['sha']])
    checked['community_commit'] = community['commit']
    progress(0, '检查全部已合并名称提交…')
    submitted = [entry for entry in upstream['entries'] if entry.get('type') == 'blob'
                 and entry['path'].startswith('submissions/') and entry['path'].endswith('.txt')]
    texts = api.blobs(UPSTREAM, submitted)
    for data in texts.values():
        claims.text(data, 'merged')
    checked['submission_blobs'] = len(texts)
    progress(0, '检查开放 PR 中尚未合并的名称…')
    pulls = api.paginate(f'/repos/{UPSTREAM}/pulls?state=open')
    checked['open_heads'] = _open_signature(pulls)
    for pr in pulls:
        number = int(pr['number'])
        detail = api.request('GET', f'/repos/{UPSTREAM}/pulls/{number}')
        if detail['head']['sha'] != pr['head']['sha'] or detail.get('changed_files', 3001) > 3000:
            raise ValueError('开放 PR 正在变化或文件清单过大，请重新预览后提交')
        files = api.paginate(f'/repos/{UPSTREAM}/pulls/{number}/files')
        if len(files) != detail['changed_files']:
            raise ValueError('开放 PR 文件清单不完整，停止投稿')
        changed = [dict(file, path=file['filename']) for file in files if file['status'] != 'removed'
                   and file['filename'].startswith('submissions/') and file['filename'].endswith('.txt')]
        for data in api.blobs(UPSTREAM, changed).values():
            claims.text(data, 'open_pr')
        if api.request('GET', f'/repos/{UPSTREAM}/pulls/{number}')['head']['sha'] != pr['head']['sha']:
            raise ValueError('检查期间开放 PR 内容发生变化，请重试')
    remaining = []
    for row in held:
        source = claims.source(row)
        if source:
            excluded[source] += 1
        else:
            remaining.append(row)
    checked['invalid_existing_rows'] = claims.invalid_rows
    return remaining, excluded, checked


def _notes(game, login, stamp, rows, local, excluded, checked, online):
    counts = Counter(row['kind'] for row in rows)
    methods = sorted({row['method_id'] for row in rows})
    stats = local['stats']; fingerprint = _digest([(row['kind'], row['hash'], row['name']) for row in rows])
    lines = [f'# Submission {stamp}', '', f'- game: {game}', f'- from: {login}',
             f'- names: {len(rows)}', '- platform: windows x86_64',
             '- confirmed on: CPU independent full-key recheck',
             f'- checked online: {str(online).lower()}',
             f'- tool: COD Name Finder {VERSION}',
             '- method source: https://github.com/ez4cywa/cod-name-finder/tree/v' + VERSION + '/finder',
             f'- upstream commit: {checked.get("upstream_commit", "not checked offline")}',
             f'- community commit: {checked.get("community_commit", "not checked offline")}',
             f'- open pull requests checked: {len(checked.get("open_heads", []))}']
    lines.extend(f'- {kind}: {count}' for kind, count in sorted(counts.items()))
    lines.extend(f'- dropped {reason}: {count}' for reason, count in sorted(excluded.items()) if count)
    lines += ['', 'Every submitted name was independently rehashed against a complete local typed target.',
              'Online submissions also require membership in this game\'s pinned upstream capture.',
              'Only name lists and this summary are uploaded; local paths, keywords, databases,',
              'source corpora and capture files are excluded.', '', '## How these were found', '',
              f'### run_{stamp}_namefinder', f'- method: cod-name-finder-verified-export',
              '- what it does: Exported complete-key discoveries; typed local evidence and upstream capture rechecked, then fresh community/merged/open-PR deduplication.',
              f'- ran for: {stats["seconds"]}s', '- duration scope: entire local run including preparation and export, not per-method hashing time',
              '- platform: windows x86_64', '- confirmed on: CPU independent full-key recheck',
              f'- game: {game}', f'- candidates tested: {stats["processed"]}',
              f'- matched: {stats.get("verified_target_matches", len(local["rows"]))}', f'- new: {len(rows)}', f'- batch fingerprint: {fingerprint[:16]}',
              f'- reused complete run cache: {str(stats.get("cache_reused", False)).lower()}',
              '- discovery methods: ' + ', '.join(methods), '',
              'The total run statistics are reported once; no per-method timings are inferred.']
    return '\n'.join(lines) + '\n'


def prepare(export_dir, *, token=None, api=None, offline=False, progress=lambda *_: None):
    local = collect_export(export_dir)
    game, rows, unsupported = _eligible(local)
    supplied = None if offline else token or (None if api is not None else get_token())
    online = not offline and bool(supplied or api)
    login = 'your-github-login'; checked = {}; excluded = Counter()
    if online:
        api = api or GitHubApi(validate_token(supplied), _cache_root(), progress=progress)
        login = _login(api.request('GET', '/user'))
        if rows:
            rows, excluded, checked = _check_network(api, game, rows, progress)
    rows.sort(key=lambda row: (row['kind'], row['hash'], row['name']))
    digest = _digest({'game': game, 'rows': [(row['kind'], row['hash'], row['name']) for row in rows]})
    base = Path(export_dir).resolve().parent/'upstream-contributions'; base.mkdir(exist_ok=True)
    stamp_path = base/('stamp-'+digest+'.txt')
    try:
        with stamp_path.open('x', encoding='ascii') as stream:
            stream.write(datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S'))
    except FileExistsError:
        pass
    stamp = stamp_path.read_text(encoding='ascii')
    if not re.fullmatch(r'\d{8}-\d{6}', stamp):
        raise ValueError('本地批次时间记录无效，请检查投稿缓存')
    title = f'[{game}] findings from {login}, {stamp} ({len(rows)} names)'
    body = _notes(game, login, stamp, rows, local, excluded + unsupported, checked, online)
    directory = base/uuid.uuid4().hex
    directory.mkdir(parents=True)
    public = directory/'public'; public.mkdir()
    files = {}
    for kind in sorted({row['kind'] for row in rows}):
        name = f'{kind}_{stamp}.txt'
        text = ''.join(f'{parse_hash(row["hash"]):x},{row["name"]}\n' for row in rows if row['kind'] == kind)
        (public/name).write_text(text, encoding='utf-8', newline='\n')
        files[name] = hashlib.sha256(text.encode('utf-8')).hexdigest()
    about = f'about_{stamp}.md'; (public/about).write_text(body, encoding='utf-8', newline='\n')
    files[about] = hashlib.sha256(body.encode('utf-8')).hexdigest()
    preview = body + '\n## Exact public name lists\n'
    for name in sorted(files):
        if name.endswith('.txt'):
            preview += '\n### ' + name + '\n\n```text\n' + (public/name).read_text(encoding='utf-8') + '```\n'
    (directory/'preview.md').write_text(preview, encoding='utf-8')
    state = {'schema': 1, 'export_dir': str(Path(export_dir).resolve()), 'game': game, 'login': login,
             'stamp': stamp, 'row_digest': digest, 'title': title, 'body': body, 'public_files': files,
             'eligible_count': len(rows), 'checked': checked}
    _write_json(directory/'submission.json', state)
    return {'status': 'ready' if rows else 'empty', 'package_dir': str(directory),
            'preview_path': str(directory/'preview.md'), 'title': title, 'body': body, 'game': game,
            'eligible_count': len(rows), 'excluded_count': sum(excluded.values()),
            'unsupported_count': sum(unsupported.values()), 'excluded': dict(excluded),
            'unsupported': dict(unsupported), 'network_checked': online,
            'submit_allowed': online and bool(rows), 'public_files': sorted(files),
            'message': '可提交的新名称已准备' if rows else '没有符合上游投稿条件的新增名称；本地导出保留'}


@contextmanager
def _submission_lock(export):
    path = Path(export).resolve().parent/'.upstream-submit.lock'
    stream = path.open('a+b')
    try:
        if path.stat().st_size == 0:
            stream.write(b'0'); stream.flush()
        stream.seek(0)
        try:
            if sys.platform == 'win32':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise ValueError('这次导出正在提交，请等待现有操作完成') from error
        try:
            yield
        finally:
            stream.seek(0)
            if sys.platform == 'win32':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)
    finally:
        stream.close()


def _load_package(directory):
    path = Path(directory).resolve()/'submission.json'
    if not path.is_file() or path.stat().st_size > MAX_PACKAGE:
        raise ValueError('提交包不存在或过大，请重新预览')
    state = json.loads(path.read_text(encoding='utf-8'))
    if state.get('schema') != 1 or not isinstance(state.get('export_dir'), str):
        raise ValueError('提交包版本无效，请重新预览')
    for name, digest in state.get('public_files', {}).items():
        if not re.fullmatch(r'(?:about|xanim|image|material|sound_asset|sound_alias)_\d{8}-\d{6}\.(?:txt|md)', name):
            raise ValueError('提交包出现未允许的文件')
        file = path.parent/'public'/name
        if file.is_symlink() or not file.is_file() or file.stat().st_size > MAX_PACKAGE or hashlib.sha256(file.read_bytes()).hexdigest() != digest:
            raise ValueError('提交预览内容已经改变，请重新预览')
    return state


def _public_payloads(directory, state):
    """Read once, check once, upload those exact bytes after network waits."""
    public = Path(directory)/'public'
    payloads = {}
    for name, digest in state['public_files'].items():
        path = public/name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_PACKAGE:
            raise ValueError('提交预览内容已经改变，请重新预览')
        with path.open('rb') as stream:
            data = stream.read(MAX_PACKAGE+1)
        if len(data) > MAX_PACKAGE or hashlib.sha256(data).hexdigest() != digest:
            raise ValueError('提交预览内容已经改变，请重新预览')
        payloads[name] = data.decode('utf-8')
    return payloads


def _fork(api, login):
    fork = f'{login}/hash-slinging-slasher'
    if fork.lower() == UPSTREAM.lower():
        return fork
    try:
        repo = api.request('GET', f'/repos/{fork}')
    except GitHubError as error:
        if error.status_code != 404:
            raise
        api.request('POST', f'/repos/{UPSTREAM}/forks', {'default_branch_only': True})
        for attempt in range(12):
            try:
                repo = api.request('GET', f'/repos/{fork}'); break
            except GitHubError as pending:
                if pending.status_code != 404 or attempt == 11:
                    raise ValueError('GitHub Fork 尚未就绪，请稍后重试；本地提交包已保留') from pending
                time.sleep(1)
    if not repo.get('fork') or repo.get('parent', {}).get('full_name', '').lower() != UPSTREAM.lower():
        raise ValueError('账号下同名仓库不是目标项目的 Fork，软件不会覆盖它')
    return fork


def _existing_pr(api, login, branch):
    pulls = api.paginate(f'/repos/{UPSTREAM}/pulls?state=all&head={login}:{branch}')
    for pr in pulls:
        if pr.get('head', {}).get('ref') == branch and pr.get('head', {}).get('repo', {}).get('owner', {}).get('login', '').lower() == login.lower():
            return pr
    return None


def submit(package_dir, *, token=None, api=None, progress=lambda *_: None):
    old = _load_package(package_dir)
    supplied = token or (None if api is not None else get_token())
    if not supplied and api is None:
        raise ValueError('创建 PR 需要 GitHub Token；本地预览与导出保留')
    api = api or GitHubApi(validate_token(supplied), _cache_root(), progress=progress)
    login = _login(api.request('GET', '/user'))
    with _submission_lock(old['export_dir']):
        # Recovery is checked before re-dedup: this run's already opened PR
        # would otherwise exclude its own rows and look like an empty batch.
        old_branch = 'codex/findings-' + old['row_digest'][:24]
        if old.get('login') == login and (existing := _existing_pr(api, login, old_branch)):
            return {'status': 'already_submitted', 'pull_request_url': existing['html_url'],
                    'submitted_count': old['eligible_count'], 'package_dir': str(package_dir),
                    'pull_request_state': existing['state']}
        prepared = prepare(old['export_dir'], token=token, api=api, progress=progress)
        if not prepared['eligible_count']:
            return {**prepared, 'submitted_count': 0, 'pull_request_url': ''}
        state = _load_package(prepared['package_dir'])
        checked = state['checked']
        # The asynchronous remote landscape can move during a long first-time
        # cache fill. Do not publish against that stale view.
        if api.request('GET', f'/repos/{UPSTREAM}/commits/HEAD')['sha'] != checked['upstream_commit'] or \
           api.request('GET', f'/repos/{COMMUNITY}/commits/HEAD')['sha'] != checked['community_commit'] or \
           _open_signature(api.paginate(f'/repos/{UPSTREAM}/pulls?state=open')) != checked['open_heads']:
            raise ValueError('排重期间上游有新提交，请重新创建 PR；提交包与本地结果已保留')
        branch = 'codex/findings-' + state['row_digest'][:24]
        if existing := _existing_pr(api, login, branch):
            return {'status': 'already_submitted', 'pull_request_url': existing['html_url'],
                    'submitted_count': state['eligible_count'], 'package_dir': prepared['package_dir'],
                    'pull_request_state': existing['state']}
        public_payloads = _public_payloads(prepared['package_dir'], state)
        progress(0, '创建名称贡献分支与 PR…')
        fork = _fork(api, login)
        pending_base = Path(old['export_dir']).resolve().parent/'upstream-contributions'
        pending_path = pending_base/('pending-'+login.lower()+'-'+state['row_digest']+'.json')
        try:
            ref = api.request('GET', f'/repos/{fork}/git/ref/heads/{branch}')
        except GitHubError as error:
            if error.status_code != 404:
                raise
            ref = None
        if ref is not None:
            # Recover an uploaded branch after a lost response without force
            # pushing, even if the upstream base advanced before this retry.
            if not pending_path.is_file() or pending_path.stat().st_size > MAX_PACKAGE:
                raise ValueError('同批次远程分支已存在但缺少本地回执，不会覆盖；请检查 Fork')
            pending = json.loads(pending_path.read_text(encoding='utf-8'))
            previous_dir = Path(pending['package_dir']).resolve()
            if not previous_dir.is_relative_to(pending_base.resolve()):
                raise ValueError('本地提交回执目录无效')
            previous_state = _load_package(previous_dir)
            journal = previous_dir/'receipt.json'
            receipt = json.loads(journal.read_text(encoding='utf-8'))
            if previous_state['row_digest'] != state['row_digest'] or previous_state['login'] != login or \
               receipt.get('commit') != ref['object']['sha']:
                raise ValueError('同批次远程分支与本地回执不符，不会强制覆盖')
            previous_commit = api.request('GET', f'/repos/{fork}/git/commits/{ref["object"]["sha"]}')
            if previous_commit['tree']['sha'] != receipt.get('tree'):
                raise ValueError('同批次远程分支内容不同，不会强制覆盖')
            # Keep freshly regenerated PR metadata; old local receipt metadata
            # is only a recovery pointer, never a source of public prose.
            prepared['package_dir'] = str(previous_dir)
        else:
            journal = Path(prepared['package_dir'])/'receipt.json'
            receipt = {'branch': branch, 'fork': fork, 'upstream_commit': checked['upstream_commit'],
                       'submitted_count': state['eligible_count'], 'pull_request_url': '', 'stage': 'prepared'}
            _write_json(journal, receipt)
            _write_json(pending_path, {'package_dir': prepared['package_dir']})
            # Keep the standard terminal _TAG_YYYYMMDD-HHMMSS folder shape;
            # upstream's derived collector uses it to attribute modern games.
            prefix = f'submissions/{login}-{state["row_digest"][:8]}_{state["game"]}_{state["stamp"]}/'
            tree = []
            for name in sorted(state['public_files']):
                blob = api.request('POST', f'/repos/{fork}/git/blobs',
                                   {'content': public_payloads[name], 'encoding': 'utf-8'})
                tree.append({'path': prefix+name, 'mode': '100644', 'type': 'blob', 'sha': blob['sha']})
            created_tree = api.request('POST', f'/repos/{fork}/git/trees', {'base_tree': checked['upstream_tree'], 'tree': tree})
            commit = api.request('POST', f'/repos/{fork}/git/commits',
                                 {'message': state['title'], 'tree': created_tree['sha'], 'parents': [checked['upstream_commit']]})
            receipt.update(stage='commit_prepared', commit=commit['sha'], tree=created_tree['sha'])
            _write_json(journal, receipt)
            api.request('POST', f'/repos/{fork}/git/refs', {'ref': 'refs/heads/'+branch, 'sha': commit['sha']})
        receipt.update(stage='branch_uploaded'); _write_json(journal, receipt)
        repo = api.request('GET', f'/repos/{UPSTREAM}')
        pr_body = state['body'] + '\nDuplicate checks were refreshed immediately before creating this PR.\n' + \
            f'Upstream commit: `{checked["upstream_commit"]}`; community commit: `{checked["community_commit"]}`.\n'
        try:
            pr = api.request('POST', f'/repos/{UPSTREAM}/pulls',
                             {'title': state['title'], 'body': pr_body, 'head': login+':'+branch,
                              'base': repo['default_branch'], 'maintainer_can_modify': True})
        except Exception:
            # A timeout can happen after GitHub has created the PR. Recover the
            # same head rather than repeating a write with an invented batch.
            pr = _existing_pr(api, login, branch)
            if pr is None:
                raise
        url = pr['html_url']
        if not re.fullmatch(r'https://github\.com/KingslayerKyle/hash-slinging-slasher/pull/[1-9][0-9]*', url):
            raise ValueError('GitHub 返回的 PR 地址不属于固定上游仓库')
        receipt.update(stage='submitted', pull_request_url=url); _write_json(journal, receipt)
        return {'status': 'submitted', 'pull_request_url': url, 'submitted_count': state['eligible_count'],
                'package_dir': prepared['package_dir'], 'message': '已创建上游名称贡献 PR；等待维护者审核'}
