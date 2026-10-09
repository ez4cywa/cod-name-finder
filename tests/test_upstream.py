"""Public contribution contract through a complete deterministic GitHub adapter."""
import hashlib
import io
import json
from pathlib import Path
import re
import struct

import pytest

from finder import upstream
from finder.github_api import GitHubError, UPSTREAM, COMMUNITY
from finder.hashing import PROFILES


def blob(data):
    return hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()


class GitHubFixture:
    def __init__(self, rows, *, community='', merged='', opened='', game='MODWAR7'):
        self.calls = []; self.data = {}; self.refs = {}; self.commits = {}; self.pull = None
        self.fail_pr = False; self.lost_pr_response = False; self.fork_exists = True
        self.head_moved = False; self.open_moved = False; self.open_fail = False
        self.fork_conflict = False; self.pr_url = f'https://github.com/{UPSTREAM}/pull/3000'
        tags = sorted({row['kind'] for row in rows})
        tag_map = {'sndasset': 'sound_asset', 'soundbankalias': 'sound_alias'}
        pool = {kind: index for index, kind in enumerate(tags, 900)}
        records = sorted((int(row['hash'], 16)&upstream.MASK63, pool[row['kind']]) for row in rows)
        raw = game.encode()
        ids = b'CODIDS'+struct.pack('<HH', 1, len(raw))+raw+struct.pack('<Q', len(records))
        ids += b''.join(struct.pack('<QH', *record) for record in records)
        census = f'{game} -- {len(records)} assets in {len(pool)} filled pools\nindex asset type assets\n'
        census += ''.join(f'{value} {tag_map.get(kind, kind)} {sum(p==value for _, p in records)}\n' for kind, value in pool.items())
        self.upstream_entries = [self.entry(f'snapshots/{game.lower()}.ids', ids),
                                 self.entry(f'snapshots/{game.lower()}.pools.txt', census.encode())]
        if merged:
            self.upstream_entries.append(self.entry('submissions/another_MODWAR7_20200101-000000/image_20200101-000000.txt', merged.encode()))
        self.community_entries = [self.entry('csv/'+name, community.encode() if index == 0 else b'')
                                  for index, name in enumerate(sorted(upstream.MODERN_TABLES))]
        self.open_files = []
        if opened:
            item = self.entry('submissions/another_MODWAR7_20200101-000001/image_20200101-000001.txt', opened.encode())
            self.open_files.append({'filename': item['path'], 'sha': item['sha'], 'status': 'added'})

    def entry(self, path, data):
        sha = blob(data); self.data[sha] = data
        return {'path': path, 'sha': sha, 'size': len(data), 'type': 'blob'}

    def tree(self, repo, ref='HEAD'):
        return {'commit': 'a'*40 if repo == UPSTREAM else 'b'*40, 'tree_sha': 'c'*40,
                'entries': self.upstream_entries if repo == UPSTREAM else self.community_entries}

    def blobs(self, repo, entries):
        return {item['sha']: self.data[item['sha']] for item in entries}

    def paginate(self, path):
        self.calls.append(('GET', path, None))
        if path.endswith('/files'):
            return self.open_files
        if 'state=all' in path:
            return [self.pull] if self.pull else []
        if path.endswith('state=open'):
            if self.open_fail:
                raise GitHubError('开放 PR 读取失败', 403)
            # A real code-only open PR must also be counted, not ignored as an
            # excuse to skip head freshness checks.
            return [{'number': 7, 'head': {'sha': 'd'*40}}]
        raise AssertionError(path)

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if path == '/user':
            return {'login': 'tester'}
        if method == 'GET' and path.endswith('/pulls/7'):
            return {'head': {'sha': 'e'*40 if self.open_moved else 'd'*40}, 'changed_files': len(self.open_files)}
        if method == 'GET' and path.endswith('/commits/HEAD'):
            return {'sha': 'f'*40 if self.head_moved else ('a'*40 if UPSTREAM in path else 'b'*40)}
        if path == '/repos/'+UPSTREAM and method == 'GET':
            return {'default_branch': 'main'}
        if path == '/repos/tester/hash-slinging-slasher' and method == 'GET':
            if not self.fork_exists:
                raise GitHubError('not found', 404)
            return {'fork': not self.fork_conflict, 'parent': {'full_name': UPSTREAM}}
        if path.endswith('/forks') and method == 'POST':
            self.fork_exists = True; return {}
        if '/git/ref/heads/' in path:
            branch = path.split('/git/ref/heads/')[1]
            if branch not in self.refs:
                raise GitHubError('not found', 404)
            return {'object': {'sha': self.refs[branch]}}
        if method == 'GET' and '/git/commits/' in path:
            return self.commits[path.rsplit('/', 1)[1]]
        if method == 'POST' and path.endswith('/git/blobs'):
            return {'sha': blob(payload['content'].encode())}
        if method == 'POST' and path.endswith('/git/trees'):
            return {'sha': hashlib.sha1(json.dumps(payload, sort_keys=True).encode()).hexdigest()}
        if method == 'POST' and path.endswith('/git/commits'):
            sha = hashlib.sha1(json.dumps(payload, sort_keys=True).encode()).hexdigest()
            self.commits[sha] = {'tree': {'sha': payload['tree']}}
            return {'sha': sha}
        if method == 'POST' and path.endswith('/git/refs'):
            self.refs[payload['ref'].removeprefix('refs/heads/')] = payload['sha']; return {}
        if method == 'POST' and path.endswith('/pulls'):
            if self.fail_pr:
                raise GitHubError('temporary failure', 503)
            self.pull = {'html_url': self.pr_url, 'state': 'open',
                         'head': {'ref': payload['head'].split(':')[1],
                                  'repo': {'owner': {'login': 'tester'}}}}
            if self.lost_pr_response:
                raise GitHubError('response lost', 503)
            return self.pull
        raise AssertionError((method, path, payload))


def row(name='rex/test_new_name', kind='image', profile='iw-resource63'):
    return {'kind': kind, 'hash': f'{PROFILES[profile].digest(name):016x}', 'name': name,
            'profile': profile, 'method_id': 'soundplans.alias_missing_family',
            'method_version': '1', 'generator_sha': '9'*64}


@pytest.fixture
def local(tmp_path, monkeypatch):
    export = tmp_path/'private-keyword-secret-source-folder'/'names-example'; export.mkdir(parents=True)
    value = {'game': 'COD2026', 'profile': 'iw-resource63', 'rows': [row()], 'rejected': {},
             'stats': {'processed': 251, 'seconds': 1.25, 'cache_reused': False}}
    monkeypatch.setattr(upstream, 'collect_export', lambda path: value)
    monkeypatch.setattr(upstream, 'get_token', lambda: None)
    return export, value


def test_offline_preview_contains_exact_public_lists_and_no_private_paths(local):
    export, data = local
    result = upstream.prepare(export)
    assert result['eligible_count'] == 1 and not result['network_checked'] and not result['submit_allowed']
    preview = Path(result['preview_path']).read_text(encoding='utf-8')
    assert data['rows'][0]['name'] in preview and 'private-keyword-secret' not in preview
    public = Path(result['package_dir'])/'public'
    assert {file.suffix for file in public.iterdir()} == {'.txt', '.md'}
    assert '- candidates tested: 251' in preview and '- duration scope:' in preview
    assert '- batch fingerprint:' in preview and '- fingerprint:' not in preview
    assert re.search(r'### run_\d{8}-\d{6}_namefinder', preview)


def test_non_ascii_names_stay_local_and_are_not_proposed(local):
    export, data = local
    data['rows'] = [row('asset/Éclair')]
    result = upstream.prepare(export)
    assert result['eligible_count'] == 0
    assert result['unsupported'] == {'upstream_non_ascii_name': 1}
    assert data['rows'][0]['name'] == 'asset/Éclair'


def test_explicit_offline_never_reads_credentials_or_network(local, monkeypatch):
    export, data = local
    def unexpected(*args, **kwargs):
        raise AssertionError('offline must not read credentials or use network')
    monkeypatch.setattr(upstream, 'get_token', unexpected)
    monkeypatch.setattr(upstream, 'GitHubApi', unexpected)
    result = upstream.prepare(export, token='ignored', offline=True)
    assert result['eligible_count'] == 1 and not result['network_checked'] and not result['submit_allowed']


@pytest.mark.parametrize('source', ['community', 'merged', 'opened'])
@pytest.mark.parametrize('claim', ['same-name', 'same-key', 'display-separators', 'high-bit-key'])
def test_fresh_claims_exclude_published_or_claimed_names(local, source, claim):
    export, data = local
    target = data['rows'][0]
    key, name = target['hash'], target['name']
    if claim == 'same-name':
        key = '1234'
    elif claim == 'same-key':
        name = 'other_name'
    elif claim == 'display-separators':
        key = '1234'; name = name.replace('/', '.')
    else:
        key = f'{int(key, 16) | 1<<63:x}'; name = 'other_name'
    api = GitHubFixture(data['rows'], **{source: f'{key},{name}\n'})
    result = upstream.prepare(export, api=api)
    assert result['status'] == 'empty' and result['excluded_count'] == 1
    assert not any(call[0] == 'POST' for call in api.calls)


def test_current_game_typed_snapshot_required(local):
    export, data = local
    api = GitHubFixture([row(data['rows'][0]['name'], 'xanim')])
    result = upstream.prepare(export, api=api)
    assert result['excluded']['upstream_snapshot_missing'] == 1
    assert result['eligible_count'] == 0


def test_full64_alias_is_preserved_while_snapshot_membership_masks_only(local):
    export, data = local
    alias = next(row(f'alias_{n}', 'soundbankalias', 'fnv1a64') for n in range(50)
                 if PROFILES['fnv1a64'].digest(f'alias_{n}') >> 63)
    data['rows'] = [alias]
    result = upstream.prepare(export, api=GitHubFixture(data['rows']))
    text = next((Path(result['package_dir'])/'public').glob('sound_alias_*.txt')).read_text()
    assert text.startswith(f'{int(alias["hash"], 16):x},') and int(text.split(',')[0], 16) >> 63


def test_partial_or_wrong_profile_alias_is_not_promoted(local):
    export, data = local
    data['rows'] = [row('alias', 'soundbankalias', 'iw-resource63')]
    result = upstream.prepare(export)
    assert result['unsupported_count'] == 1 and result['eligible_count'] == 0


def test_unsupported_kind_stays_local(local):
    export, data = local
    data['rows'].append(row('bank', 'soundbank'))
    result = upstream.prepare(export)
    assert result['eligible_count'] == 1 and result['unsupported_count'] == 1


def test_comma_names_are_unquoted_upstream_split_first_format(local):
    export, data = local
    data['rows'] = [row('rex/name,with_comma')]
    result = upstream.prepare(export, api=GitHubFixture(data['rows']))
    text = next((Path(result['package_dir'])/'public').glob('image_*.txt')).read_text()
    assert text == f'{int(data["rows"][0]["hash"], 16):x},rex/name,with_comma\n'


@pytest.mark.parametrize('mode', ['open_fail', 'open_moved'])
def test_open_pr_incomplete_or_moving_checks_block_all_writes(local, mode):
    export, data = local
    package = upstream.prepare(export)
    api = GitHubFixture(data['rows']); setattr(api, mode, True)
    with pytest.raises((GitHubError, ValueError)):
        upstream.submit(package['package_dir'], api=api)
    assert not any(call[0] == 'POST' for call in api.calls)


def test_submit_rechecks_fresh_community_after_preview(local):
    export, data = local
    api = GitHubFixture(data['rows'])
    package = upstream.prepare(export, api=api)
    new_table = api.entry(api.community_entries[0]['path'], f'{data["rows"][0]["hash"]},published_now\n'.encode())
    api.community_entries[0] = new_table
    result = upstream.submit(package['package_dir'], api=api)
    assert result['status'] == 'empty' and result['submitted_count'] == 0
    assert not any(call[0] == 'POST' for call in api.calls)


def test_changed_preview_is_rejected_before_network_writes(local):
    export, data = local
    result = upstream.prepare(export)
    next((Path(result['package_dir'])/'public').glob('*.txt')).write_text('tampered')
    api = GitHubFixture(data['rows'])
    with pytest.raises(ValueError, match='改变'):
        upstream.submit(result['package_dir'], api=api)
    assert not api.calls


def test_submit_preserves_base_and_publishes_only_generated_public_files(local):
    export, data = local
    api = GitHubFixture(data['rows'])
    package = upstream.prepare(export, api=api)
    result = upstream.submit(package['package_dir'], api=api)
    assert result['status'] == 'submitted' and result['submitted_count'] == 1
    tree = next(payload for method, path, payload in api.calls if method == 'POST' and path.endswith('/git/trees'))
    assert tree['base_tree'] == 'c'*40 and len(tree['tree']) == 2
    for entry in tree['tree']:
        assert re.match(r'submissions/tester-[a-f0-9]{8}_MODWAR7_\d{8}-\d{6}/(?:about|image)_', entry['path'])
        assert entry['mode'] == '100644' and entry['type'] == 'blob'
    commit = next(payload for method, path, payload in api.calls if method == 'POST' and path.endswith('/git/commits'))
    assert commit['parents'] == ['a'*40]
    assert not any(method in ('PATCH', 'PUT', 'DELETE') for method, _, _ in api.calls)
    uploaded = '\n'.join(json.dumps(payload) for method, _, payload in api.calls if method == 'POST')
    assert 'private-keyword-secret' not in uploaded and 'work.sqlite' not in uploaded
    assert 'manifest.json' not in uploaded and 'evidence.jsonl' not in uploaded


def test_repeated_submit_recovers_existing_pr_without_duplicate_writes(local):
    export, data = local; api = GitHubFixture(data['rows'])
    package = upstream.prepare(export, api=api)
    first = upstream.submit(package['package_dir'], api=api)
    writes = len([call for call in api.calls if call[0] == 'POST'])
    second = upstream.submit(package['package_dir'], api=api)
    assert second['status'] == 'already_submitted' and second['pull_request_url'] == first['pull_request_url']
    assert len([call for call in api.calls if call[0] == 'POST']) == writes


def test_upload_uses_verified_bytes_if_preview_changes_during_network_waits(local):
    export, data = local; api = GitHubFixture(data['rows'])
    package = upstream.prepare(export, api=api)
    def progress(number, message):
        if message.startswith('创建名称贡献分支'):
            for path in export.parent.glob('upstream-contributions/*/public/*.txt'):
                path.write_text('unverified replacement', encoding='utf-8')
    result = upstream.submit(package['package_dir'], api=api, progress=progress)
    assert result['status'] == 'submitted'
    contents = [payload['content'] for method, path, payload in api.calls
                if method == 'POST' and path.endswith('/git/blobs')]
    assert all('unverified replacement' not in content for content in contents)
    assert any(data['rows'][0]['name'] in content for content in contents)


def test_lost_pr_response_recovers_same_head(local):
    export, data = local; api = GitHubFixture(data['rows']); api.lost_pr_response = True
    package = upstream.prepare(export, api=api)
    result = upstream.submit(package['package_dir'], api=api)
    assert result['status'] == 'submitted'
    assert len([call for call in api.calls if call[0] == 'POST' and call[1].endswith('/pulls')]) == 1


def test_uploaded_branch_reused_after_pr_failure(local):
    export, data = local; api = GitHubFixture(data['rows']); api.fail_pr = True
    package = upstream.prepare(export, api=api)
    with pytest.raises(GitHubError):
        upstream.submit(package['package_dir'], api=api)
    git_writes = [call for call in api.calls if call[0] == 'POST' and '/git/' in call[1]]
    api.fail_pr = False
    result = upstream.submit(package['package_dir'], api=api)
    assert result['status'] == 'submitted'
    assert [call for call in api.calls if call[0] == 'POST' and '/git/' in call[1]] == git_writes


def test_recovered_branch_uses_fresh_title_and_body_if_old_metadata_is_modified(local):
    export, data = local; api = GitHubFixture(data['rows']); api.fail_pr = True
    package = upstream.prepare(export, api=api)
    with pytest.raises(GitHubError):
        upstream.submit(package['package_dir'], api=api)
    pending_path = next((export.parent/'upstream-contributions').glob('pending-*.json'))
    pending = json.loads(pending_path.read_text(encoding='utf-8'))
    previous_dir = Path(pending['package_dir'])
    state_path = previous_dir/'submission.json'
    state = json.loads(state_path.read_text(encoding='utf-8'))
    trusted_title, trusted_body = state['title'], state['body']
    state.update(title='unverified title replacement', body='unverified body replacement')
    state_path.write_text(json.dumps(state), encoding='utf-8')
    git_writes = [call for call in api.calls if call[0] == 'POST' and '/git/' in call[1]]

    api.fail_pr = False
    result = upstream.submit(package['package_dir'], api=api)

    assert result['status'] == 'submitted' and Path(result['package_dir']) == previous_dir
    assert [call for call in api.calls if call[0] == 'POST' and '/git/' in call[1]] == git_writes
    published = [payload for method, path, payload in api.calls
                 if method == 'POST' and path.endswith('/pulls')][-1]
    assert published['title'] == trusted_title
    assert published['body'].startswith(trusted_body)
    assert 'unverified title replacement' not in published['title']
    assert 'unverified body replacement' not in published['body']


def test_landscape_moves_during_checks_no_publication(local):
    export, data = local; api = GitHubFixture(data['rows']); api.head_moved = True
    package = upstream.prepare(export)
    with pytest.raises(ValueError, match='新提交'):
        upstream.submit(package['package_dir'], api=api)
    assert not any(call[0] == 'POST' for call in api.calls)


def test_same_name_non_fork_repo_is_never_overwritten(local):
    export, data = local; api = GitHubFixture(data['rows']); api.fork_conflict = True
    package = upstream.prepare(export)
    with pytest.raises(ValueError, match='不会覆盖'):
        upstream.submit(package['package_dir'], api=api)
    assert not any(call[0] == 'POST' for call in api.calls)


def test_fork_created_when_missing(local):
    export, data = local; api = GitHubFixture(data['rows']); api.fork_exists = False
    package = upstream.prepare(export)
    assert upstream.submit(package['package_dir'], api=api)['status'] == 'submitted'
    assert len([call for call in api.calls if call[0] == 'POST' and call[1].endswith('/forks')]) == 1


def test_missing_token_keeps_preview(local):
    export, _ = local; package = upstream.prepare(export)
    with pytest.raises(ValueError, match='需要 GitHub Token'):
        upstream.submit(package['package_dir'])
    assert Path(package['preview_path']).is_file()


def test_cli_uses_stdin_credentials_without_token_argument(local, monkeypatch, capsys):
    from finder.__main__ import _dispatch
    export, _ = local
    monkeypatch.setattr('sys.stdin', io.StringIO('{"token":"", "remember_token": false}'))
    assert _dispatch(['upstream', 'prepare', '--export', str(export), '--stdin'], {}) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['eligible_count'] == 1 and not result['network_checked']


@pytest.mark.parametrize('body', ['[]', '{"token":42}', '{"token":"x","remember_token":"yes"}', '{"token":"x","unexpected":1}', ' '*8193])
def test_cli_rejects_malformed_secret_input(local, monkeypatch, body):
    from finder.__main__ import _dispatch
    monkeypatch.setattr('sys.stdin', io.StringIO(body))
    with pytest.raises(ValueError):
        _dispatch(['upstream', 'auth-status', '--stdin'], {})
