"""Synthetic immutable Git objects verify transport, completeness and credential boundaries."""
import hashlib
import json
from pathlib import Path
import re
from urllib import error, parse

import pytest

from finder import github_api as github


def blob(data, path='submissions/test/image_20261009-000000.txt'):
    sha = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
    return {'sha': sha, 'size': len(data), 'path': path, 'type': 'blob', 'mode': '100644'}


def reply(value, code=200):
    return code, {}, json.dumps(value).encode()


@pytest.fixture
def api(tmp_path):
    return github.GitHubApi('synthetic_test_token', tmp_path)


@pytest.mark.parametrize('path', [
    'https://evil.invalid/repos/x/y', '//evil.invalid/x', '/repos/other/hash-slinging-slasher',
    '/repos/KingslayerKyle/other', '/repos/KingslayerKyle/hash-slinging-slasher/../other',
    '/repos/KingslayerKyle/hash-slinging-slasher/%2e%2e/x',
    '/repos/KingslayerKyle/hash-slinging-slasher?q=%0aAuthorization:x',
    '/repos/KingslayerKyle/hash-slinging-slasher\\evil', '/graphql', '/user?x=1',
])
def test_rejects_unapproved_origins_repositories_and_ambiguous_paths(api, monkeypatch, path):
    monkeypatch.setattr(api, '_transport', lambda *args: pytest.fail('must reject before networking'))
    with pytest.raises(github.GitHubError):
        api.request('GET', path)


def test_only_authenticated_login_can_access_its_fork(api, monkeypatch):
    seen = []

    def transport(req, limit):
        seen.append(req.full_url)
        return reply({'login': 'fixture-user'} if req.full_url.endswith('/user') else {'ok': True})

    monkeypatch.setattr(api, '_transport', transport)
    with pytest.raises(github.GitHubError):
        api.request('GET', '/repos/fixture-user/hash-slinging-slasher')
    assert api.request('GET', '/user')['login'] == api.login == 'fixture-user'
    assert api.request('GET', '/repos/fixture-user/hash-slinging-slasher') == {'ok': True}
    with pytest.raises(github.GitHubError):
        api.request('GET', '/repos/fixture-user/cod-name-db')
    assert len(seen) == 2
    with pytest.raises(AttributeError):
        api.login = 'other-user'


def test_paginate_reads_every_page_and_preserves_query(api, monkeypatch):
    seen = []

    def transport(req, limit):
        query = parse.parse_qs(parse.urlsplit(req.full_url).query)
        seen.append(query)
        page = int(query['page'][0])
        return reply(list(range(100)) if page == 1 else ['last'])

    monkeypatch.setattr(api, '_transport', transport)
    assert len(api.paginate('/repos/' + github.UPSTREAM + '/pulls?state=open&per_page=2&page=9')) == 101
    assert [q['page'] for q in seen] == [['1'], ['2']]
    assert all(q['per_page'] == ['100'] and q['state'] == ['open'] for q in seen)


def test_paginate_never_returns_partial_results_on_later_failure(api, monkeypatch):
    calls = []

    def transport(req, limit):
        calls.append(req)
        return reply(list(range(100))) if len(calls) == 1 else (403, {}, b'private synthetic_test_token')

    monkeypatch.setattr(api, '_transport', transport)
    with pytest.raises(github.GitHubError) as caught:
        api.paginate('/repos/' + github.UPSTREAM + '/pulls')
    assert caught.value.status_code == 403 and 'synthetic_test_token' not in str(caught.value)


def test_paginate_at_limit_fails_closed(api, monkeypatch):
    monkeypatch.setattr(api, '_transport', lambda *args: reply(list(range(100))))
    with pytest.raises(github.GitHubError, match='100 页'):
        api.paginate('/repos/' + github.UPSTREAM + '/pulls')


def test_tree_pins_recursive_read_to_resolved_commit(api, monkeypatch):
    commit, tree = 'a' * 40, 'b' * 40
    seen = []

    def transport(req, limit):
        seen.append(req.full_url)
        if '/commits/' in req.full_url:
            return reply({'sha': commit, 'commit': {'tree': {'sha': tree}}})
        return reply({'sha': tree, 'truncated': False, 'tree': [blob(b'1,fixture\n')]})

    monkeypatch.setattr(api, '_transport', transport)
    result = api.tree(github.UPSTREAM, 'main')
    assert result['commit'] == commit and result['tree_sha'] == tree
    assert seen[-1].endswith('/git/trees/' + tree + '?recursive=1')


@pytest.mark.parametrize('data', [
    {'sha': 'b' * 40, 'truncated': True, 'tree': []},
    {'sha': 'b' * 40, 'tree': []},
    {'sha': 'c' * 40, 'truncated': False, 'tree': []},
    {'sha': 'b' * 40, 'truncated': False, 'tree': [blob(b'x', '../escape')]},
])
def test_tree_refuses_truncation_wrong_tree_or_unsafe_paths(api, monkeypatch, data):
    monkeypatch.setattr(api, '_transport', lambda req, limit: reply(
        {'sha': 'a' * 40, 'commit': {'tree': {'sha': 'b' * 40}}} if '/commits/' in req.full_url else data))
    with pytest.raises(github.GitHubError):
        api.tree(github.UPSTREAM)


def graphql_transport(objects, calls, *, mutations=None):
    def transport(req, limit):
        calls.append((req.full_url, req.headers, limit))
        if req.full_url.endswith('/graphql'):
            query = json.loads(req.data)['query']
            found = re.findall(r'(b\d+): object\(oid: "([0-9a-f]{40})"\)', query)
            repository = {}
            for alias, sha in found:
                data = objects[sha]
                value = {'oid': sha, 'byteSize': len(data), 'isBinary': False,
                         'isTruncated': False, 'text': data.decode('utf-8')}
                if mutations:
                    mutations(value)
                repository[alias] = value
            return reply({'data': {'repository': repository}})
        sha = req.full_url.rsplit('/', 1)[1]
        return 200, {}, objects[sha]
    return transport


def test_graphql_batches_at_most_50_and_cached_sha_never_refetches(api, monkeypatch):
    objects = {blob(f'{i},fixture_{i}\n'.encode())['sha']: f'{i},fixture_{i}\n'.encode() for i in range(51)}
    entries = [blob(data) for data in objects.values()]
    calls = []
    monkeypatch.setattr(api, '_transport', graphql_transport(objects, calls))
    assert api.blobs(github.UPSTREAM, entries + entries) == objects
    assert len(calls) == 2
    monkeypatch.setattr(api, '_transport', lambda *args: pytest.fail('verified cache must be reused'))
    assert api.blobs(github.UPSTREAM, entries) == objects


def test_corrupt_cache_is_replaced_only_by_verified_network_content(api, monkeypatch):
    data = b'abc,fixture\n'
    entry = blob(data)
    cache = api.cache_dir / 'blobs' / entry['sha'][:2] / entry['sha']
    cache.parent.mkdir(parents=True)
    cache.write_bytes(b'x' * len(data))
    monkeypatch.setattr(api, '_transport', graphql_transport({entry['sha']: data}, []))
    assert api.blobs(github.UPSTREAM, [entry])[entry['sha']] == data
    assert cache.read_bytes() == data


@pytest.mark.parametrize('mutate', [lambda v: v.update(isTruncated=True, text=''),
                                    lambda v: v.update(isBinary=True, text=None),
                                    lambda v: v.update(text=None)])
def test_graphql_unavailable_text_falls_back_to_immutable_api_raw_blob(api, monkeypatch, mutate):
    data = b'abc,fixture\n'
    entry = blob(data)
    calls = []
    monkeypatch.setattr(api, '_transport', graphql_transport({entry['sha']: data}, calls, mutations=mutate))
    assert api.blobs(github.UPSTREAM, [entry])[entry['sha']] == data
    assert len(calls) == 2 and '/git/blobs/' in calls[-1][0]
    assert all(url.startswith('https://api.github.com/') for url, _, _ in calls)
    assert calls[-1][1]['Accept'] == 'application/vnd.github.raw+json'


def test_large_blob_uses_raw_api_without_graphql(api, monkeypatch):
    data = b'x' * (github.SMALL_BLOB + 1)
    entry = blob(data)
    calls = []
    monkeypatch.setattr(api, '_transport', graphql_transport({entry['sha']: data}, calls))
    assert api.blobs(github.UPSTREAM, [entry])[entry['sha']] == data
    assert len(calls) == 1 and '/git/blobs/' in calls[0][0]


def test_pull_request_entry_without_size_resolves_metadata_before_text_and_reuses_cache(api, monkeypatch):
    data = b'abc,fixture\n'
    entry = blob(data)
    del entry['size']
    queries = []
    transport = graphql_transport({entry['sha']: data}, [])

    def inspect(req, limit):
        queries.append(json.loads(req.data)['query'])
        return transport(req, limit)

    monkeypatch.setattr(api, '_transport', inspect)
    assert api.blobs(github.UPSTREAM, [entry]) == {entry['sha']: data}
    assert len(queries) == 2 and ' text ' not in queries[0] and ' text ' in queries[1]
    monkeypatch.setattr(api, '_transport', lambda *args: pytest.fail('unknown size cache must verify itself'))
    assert api.blobs(github.UPSTREAM, [entry]) == {entry['sha']: data}


def test_unknown_size_large_blob_fetches_only_metadata_then_raw(api, monkeypatch):
    data = b'x' * (github.SMALL_BLOB + 1)
    entry = blob(data)
    del entry['size']
    calls = []
    monkeypatch.setattr(api, '_transport', graphql_transport({entry['sha']: data}, calls))
    assert api.blobs(github.UPSTREAM, [entry])[entry['sha']] == data
    assert len(calls) == 2 and calls[0][0].endswith('/graphql') and '/git/blobs/' in calls[-1][0]


def test_unknown_size_total_is_checked_after_metadata_before_any_file_fetch(api, monkeypatch):
    data = b'abc,fixture\n'
    entry = blob(data)
    del entry['size']
    monkeypatch.setattr(github, 'MAX_BLOBS_TOTAL', 2)
    calls = []
    monkeypatch.setattr(api, '_transport', graphql_transport({entry['sha']: data}, calls))
    with pytest.raises(github.GitHubError, match='1 GiB'):
        api.blobs(github.UPSTREAM, [entry])
    assert len(calls) == 1
    assert not list(api.cache_dir.rglob(entry['sha']))


def test_graphql_text_batches_also_bound_aggregate_bytes(api, monkeypatch):
    data = [b'x' * 100 + bytes([i + 65]) for i in range(4)]
    objects = {blob(d)['sha']: d for d in data}
    monkeypatch.setattr(github, 'MAX_JSON', 8 * 180)
    calls = []
    monkeypatch.setattr(api, '_transport', graphql_transport(objects, calls))
    assert api.blobs(github.UPSTREAM, [blob(d) for d in data]) == objects
    assert len(calls) == 4


@pytest.mark.parametrize('mutate', [lambda v: v.update(oid='a' * 40),
                                    lambda v: v.update(byteSize=v['byteSize'] + 1),
                                    lambda v: v.update(text='corrupt'),
                                    lambda v: v.update(isBinary='false')])
def test_graphql_metadata_and_git_content_must_match(api, monkeypatch, mutate):
    data = b'abc,fixture\n'
    entry = blob(data)
    monkeypatch.setattr(api, '_transport', graphql_transport({entry['sha']: data}, [], mutations=mutate))
    with pytest.raises(github.GitHubError):
        api.blobs(github.UPSTREAM, [entry])
    assert not list(api.cache_dir.rglob(entry['sha']))


def test_batch_graphql_error_never_creates_a_verified_empty_cache(api, monkeypatch):
    monkeypatch.setattr(api, '_transport', lambda *args: reply({'errors': [{'message': 'secret synthetic_test_token'}]}))
    with pytest.raises(github.GitHubError) as caught:
        api.blobs(github.UPSTREAM, [blob(b'x')])
    assert 'synthetic_test_token' not in str(caught.value)
    assert not list(api.cache_dir.rglob('blobs'))


def test_malformed_graphql_data_is_rejected_without_leaking_response(api, monkeypatch):
    monkeypatch.setattr(api, '_transport', lambda *args: reply({'data': ['synthetic_test_token']}))
    with pytest.raises(github.GitHubError) as caught:
        api.blobs(github.UPSTREAM, [blob(b'x')])
    assert 'synthetic_test_token' not in str(caught.value)


def test_raw_blob_corruption_fails_closed(api, monkeypatch):
    monkeypatch.setattr(github, 'SMALL_BLOB', 0)
    monkeypatch.setattr(api, '_transport', lambda *args: (200, {}, b'y'))
    with pytest.raises(github.GitHubError, match='校验失败'):
        api.blobs(github.UPSTREAM, [blob(b'x')])


@pytest.mark.parametrize('entry', [
    {'sha': 'a' * 40, 'size': github.MAX_BLOB + 1, 'path': 'x'},
    {'sha': 'a' * 40, 'size': True, 'path': 'x'},
    {'sha': 'a' * 40, 'size': 1, 'path': 'x', 'mode': '120000'},
    {'sha': 'a' * 40, 'size': 1, 'path': '../x'},
    {'sha': '../escape', 'size': 1, 'path': 'x'},
])
def test_blob_manifest_is_bounded_before_transport(api, monkeypatch, entry):
    monkeypatch.setattr(api, '_transport', lambda *args: pytest.fail('invalid manifest must not fetch'))
    with pytest.raises(github.GitHubError):
        api.blobs(github.UPSTREAM, [entry])


def test_total_blob_limit_counts_unique_shas_and_rejects_before_reads(api, monkeypatch):
    monkeypatch.setattr(github, 'MAX_BLOBS_TOTAL', 2)
    monkeypatch.setattr(api, '_transport', lambda *args: pytest.fail('must reject before networking'))
    with pytest.raises(github.GitHubError, match='1 GiB'):
        api.blobs(github.UPSTREAM, [blob(b'one'), blob(b'two')])


@pytest.mark.parametrize('status', [401, 403, 429, 302])
def test_actual_urllib_http_errors_and_redirects_never_echo_response_or_token(api, monkeypatch, status):
    class Opener:
        def open(self, req, timeout):
            raise error.HTTPError(req.full_url, status, 'synthetic_test_token', {}, None)
    monkeypatch.setattr(github.http, 'build_opener', lambda *args: Opener())
    with pytest.raises(github.GitHubError) as caught:
        api.request('GET', '/user')
    assert caught.value.status_code == status
    assert 'synthetic_test_token' not in str(caught.value)
    assert github._NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.invalid') is None


def test_json_response_size_limit_and_non_json_fail_closed(api, monkeypatch):
    monkeypatch.setattr(github, 'MAX_JSON', 5)
    # Exchange's default limit is fixed at definition; transport must still enforce its supplied limit.
    monkeypatch.setattr(api, '_transport', lambda req, limit: (200, {}, b'not-json'))
    with pytest.raises(github.GitHubError, match='JSON'):
        api.request('GET', '/user')


def test_actual_response_read_has_a_hard_byte_limit(api, monkeypatch):
    class Response:
        status = 200
        headers = {}
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def geturl(self): return 'https://api.github.com/user'
        def read(self, n):
            assert n == github.MAX_JSON + 1
            return b'x' * n
    class Opener:
        def open(self, *args, **kwargs): return Response()
    monkeypatch.setattr(github.http, 'build_opener', lambda *args: Opener())
    with pytest.raises(github.GitHubError, match='超过'):
        api.request('GET', '/user')
