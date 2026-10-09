"""Bounded GitHub transport and immutable public-source blob caching.

Only GitHub's API origin receives a token. Redirects are refused, including
same-origin redirects, so an API response cannot forward credentials elsewhere.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from urllib import error, parse, request as http

from .github_credentials import validate_token

UPSTREAM = 'KingslayerKyle/hash-slinging-slasher'
COMMUNITY = 'echo000/cod-name-db'
API_ORIGIN = 'https://api.github.com'
MAX_JSON = 32 * 1024 * 1024
MAX_BLOB = 128 * 1024 * 1024
MAX_BLOBS_TOTAL = 1024 * 1024 * 1024
SMALL_BLOB = 512 * 1024
_SHA = re.compile(r'[0-9a-f]{40}\Z')
_LOGIN = re.compile(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?\Z')


class GitHubError(RuntimeError):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class _NoRedirect(http.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _blob_sha(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode('ascii') + b'\0' + data).hexdigest()


def _sha(value):
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise GitHubError('GitHub 返回了无效的 Git 对象标识')
    return value


class GitHubApi:
    def __init__(self, token, cache_dir, progress=lambda n, m: None):
        self._token = validate_token(token)
        self.cache_dir = Path(cache_dir)
        self.progress = progress
        self._login = None

    @property
    def login(self):
        return self._login

    def _repo(self, repo):
        if not isinstance(repo, str) or len(repo.split('/')) != 2:
            raise GitHubError('不允许访问此 GitHub 仓库')
        owner, name = repo.split('/')
        if not _LOGIN.fullmatch(owner) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', name):
            raise GitHubError('GitHub 仓库名称无效')
        if repo.lower() in (UPSTREAM.lower(), COMMUNITY.lower()):
            return repo
        if (self.login and owner.lower() == self.login.lower()
                and name == UPSTREAM.split('/')[1]):
            return repo
        raise GitHubError('仅允许访问上游、社区数据库及当前登录账户的投稿 fork')

    def _path(self, path, method, graphql=False):
        if (not isinstance(path, str) or not path.startswith('/') or path.startswith('//')
                or len(path) > 8192 or not path.isascii()
                or any(ord(c) <= 32 or ord(c) == 127 for c in path) or '\\' in path):
            raise GitHubError('GitHub API 路径无效')
        parts = parse.urlsplit(path)
        decoded = parse.unquote(parts.path)
        if (parts.scheme or parts.netloc or parts.fragment or '\\' in decoded
                or any(ord(c) < 32 or ord(c) == 127 for c in parse.unquote(path))
                or any(c in ('.', '..') for c in decoded.split('/'))):
            raise GitHubError('GitHub API 路径无效')
        if parts.path == '/user' and method == 'GET' and not parts.query:
            return path
        if graphql and parts.path == '/graphql' and method == 'POST' and not parts.query:
            return path
        fields = parts.path.split('/')
        if len(fields) < 4 or fields[1] != 'repos':
            raise GitHubError('不允许访问此 GitHub API 路径')
        self._repo('/'.join(fields[2:4]))
        return path

    @staticmethod
    def _http_error(code):
        messages = {
            401: 'GitHub 令牌无效或登录已失效，请重新登录（401）',
            403: 'GitHub 拒绝访问：权限不足或 API 限流，请检查令牌权限并稍后重试（403）',
            404: 'GitHub 资源不存在或当前账户无权访问（404）',
            429: 'GitHub 请求过于频繁，请稍后重试（429）',
        }
        if 300 <= code < 400:
            return GitHubError('GitHub 返回重定向，已停止请求以保护登录凭据', code)
        return GitHubError(messages.get(code, f'GitHub 请求失败（HTTP {code}），请稍后重试'), code)

    def _transport(self, req, limit):
        """The sole HTTP seam; tests replace it without networking or real credentials."""
        try:
            with http.build_opener(_NoRedirect()).open(req, timeout=45) as response:
                if parse.urlsplit(response.geturl()).netloc != 'api.github.com':
                    raise GitHubError('GitHub 响应来源无效，已停止请求')
                status = response.status
                if not 200 <= status < 300:
                    raise self._http_error(status)
                length = response.headers.get('Content-Length')
                if length is not None and int(length) > limit:
                    raise GitHubError('GitHub 响应超过允许大小，已停止请求')
                body = response.read(limit + 1)
                if len(body) > limit:
                    raise GitHubError('GitHub 响应超过允许大小，已停止请求')
                return status, response.headers, body
        except error.HTTPError as exc:
            code = exc.code
            exc.close()
            raise self._http_error(code) from None
        except (error.URLError, OSError, TimeoutError, ValueError):
            raise GitHubError('无法连接 GitHub，请检查网络并稍后重试') from None

    def _exchange(self, method, path, payload=None, *, raw=False, graphql=False, limit=MAX_JSON):
        if method not in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE'):
            raise GitHubError('不支持此 GitHub 请求方法')
        path = self._path(path, method, graphql)
        headers = {'Authorization': 'Bearer ' + self._token,
                   'Accept': 'application/vnd.github.raw+json' if raw else 'application/vnd.github+json',
                   'Accept-Encoding': 'identity', 'User-Agent': 'CODNameFinder-UpstreamSubmission',
                   'X-GitHub-Api-Version': '2022-11-28'}
        try:
            body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode('utf-8')
        except (TypeError, ValueError, UnicodeError):
            raise GitHubError('GitHub 请求数据无效') from None
        if body is not None:
            if len(body) > MAX_JSON:
                raise GitHubError('GitHub 请求数据超过允许大小')
            headers['Content-Type'] = 'application/json; charset=utf-8'
        status, _, data = self._transport(http.Request(API_ORIGIN + path, data=body, headers=headers,
                                                     method=method), limit)
        if not 200 <= status < 300:
            raise self._http_error(status)
        if not isinstance(data, bytes) or len(data) > limit:
            raise GitHubError('GitHub 响应无效或超过允许大小')
        if raw:
            return data
        if not data and status == 204:
            return None
        try:
            return json.loads(data.decode('utf-8'))
        except (UnicodeError, ValueError, RecursionError):
            raise GitHubError('GitHub 返回了无效的 JSON 数据') from None

    def request(self, method, path, payload=None):
        method = method.upper() if isinstance(method, str) else ''
        result = self._exchange(method, path, payload)
        if method == 'GET' and path == '/user':
            login = result.get('login') if isinstance(result, dict) else None
            if not isinstance(login, str) or not _LOGIN.fullmatch(login):
                raise GitHubError('GitHub 未返回有效的登录账户')
            self._login = login
        return result

    def paginate(self, path):
        self._path(path, 'GET')
        parts = parse.urlsplit(path)
        query = [(k, v) for k, v in parse.parse_qsl(parts.query, keep_blank_values=True)
                 if k not in ('page', 'per_page')]
        result = []
        for page in range(1, 101):
            url = parts.path + '?' + parse.urlencode(query + [('per_page', 100), ('page', page)])
            batch = self.request('GET', url)
            if not isinstance(batch, list) or len(batch) > 100:
                raise GitHubError('GitHub 分页数据无效，不能证明已完成去重检查')
            result.extend(batch)
            if len(batch) < 100:
                return result
        raise GitHubError('GitHub 分页超过 100 页，已停止以避免遗漏去重记录')

    def tree(self, repo, ref='HEAD'):
        repo = self._repo(repo)
        if (not isinstance(ref, str) or not 1 <= len(ref) <= 200 or not ref.isascii()
                or any(ord(c) <= 32 or ord(c) == 127 for c in ref)):
            raise GitHubError('GitHub 提交引用无效')
        commit = self.request('GET', f'/repos/{repo}/commits/{parse.quote(ref, safe="")}')
        try:
            commit_sha = _sha(commit['sha'])
            tree_sha = _sha(commit['commit']['tree']['sha'])
        except (KeyError, TypeError):
            raise GitHubError('GitHub 未返回完整的提交信息') from None
        data = self.request('GET', f'/repos/{repo}/git/trees/{tree_sha}?recursive=1')
        if (not isinstance(data, dict) or data.get('sha') != tree_sha
                or data.get('truncated') is not False or not isinstance(data.get('tree'), list)):
            raise GitHubError('GitHub 文件树不完整，不能证明已完成去重检查')
        entries = data['tree']
        if len(entries) > 200_000:
            raise GitHubError('GitHub 文件树超过允许条目数')
        for entry in entries:
            if not isinstance(entry, dict) or entry.get('type') not in ('blob', 'tree', 'commit'):
                raise GitHubError('GitHub 文件树包含无效条目')
            _sha(entry.get('sha'))
            self._file_path(entry.get('path'))
        return {'commit': commit_sha, 'tree_sha': tree_sha, 'entries': entries}

    @staticmethod
    def _file_path(path):
        if (not isinstance(path, str) or not path or path.startswith('/') or '\\' in path
                or any(ord(c) < 32 or ord(c) == 127 for c in path)
                or any(p in ('', '.', '..') for p in path.split('/'))):
            raise GitHubError('GitHub 文件路径无效')

    def _cached(self, sha, size):
        path = self.cache_dir / 'blobs' / sha[:2] / sha
        try:
            actual_size = path.stat().st_size
            if not 0 <= actual_size <= MAX_BLOB or (size is not None and actual_size != size):
                return None
            with path.open('rb') as stream:
                data = stream.read(actual_size + 1)
        except OSError:
            return None
        return data if len(data) == actual_size and _blob_sha(data) == sha else None

    def _save(self, sha, data):
        directory = self.cache_dir / 'blobs' / sha[:2]
        temporary = None
        try:
            directory.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=directory, prefix='.incoming-', delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(data)
            os.replace(temporary, directory / sha)
        except OSError:
            raise GitHubError('无法写入 GitHub 内容缓存，请检查缓存目录权限') from None
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def _raw_blob(self, repo, sha, size):
        data = self._exchange('GET', f'/repos/{repo}/git/blobs/{sha}', raw=True, limit=size)
        if len(data) != size or _blob_sha(data) != sha:
            raise GitHubError('GitHub 文件内容校验失败，不能使用不完整的去重记录')
        return data

    def _graphql_blobs(self, repo, items, *, text=True):
        owner, name = repo.split('/')
        fields = 'oid byteSize isBinary isTruncated' + (' text' if text else '')
        objects = ' '.join(f'b{i}: object(oid: "{sha}") {{ ... on Blob {{ {fields} }} }}'
                           for i, (sha, _) in enumerate(items))
        query = 'query { repository(owner: ' + json.dumps(owner) + ', name: ' + json.dumps(name) + ') { ' + objects + ' } }'
        response = self._exchange('POST', '/graphql', {'query': query}, graphql=True)
        if not isinstance(response, dict) or response.get('errors'):
            raise GitHubError('GitHub 批量读取失败，不能证明已完成去重检查')
        data = response.get('data')
        repository = data.get('repository') if isinstance(data, dict) else None
        if not isinstance(repository, dict):
            raise GitHubError('GitHub 未返回完整的批量文件内容')
        values = []
        for i, (sha, size) in enumerate(items):
            value = repository.get(f'b{i}')
            if (not isinstance(value, dict) or value.get('oid') != sha
                    or type(value.get('byteSize')) is not int or not 0 <= value['byteSize'] <= MAX_BLOB
                    or (size is not None and value['byteSize'] != size)
                    or type(value.get('isBinary')) is not bool
                    or type(value.get('isTruncated')) is not bool):
                raise GitHubError('GitHub 批量文件元数据校验失败')
            values.append(value)
        return values

    def _small_blobs(self, repo, items):
        result = {}
        for (sha, size), value in zip(items, self._graphql_blobs(repo, items)):
            text = value.get('text')
            if value['isBinary'] or value['isTruncated'] or text is None:
                result[sha] = self._raw_blob(repo, sha, size)
                continue
            if not isinstance(text, str):
                raise GitHubError('GitHub 返回了无效的文件内容')
            try:
                data = text.encode('utf-8')
            except UnicodeError:
                raise GitHubError('GitHub 返回了无效的 UTF-8 文件内容') from None
            if len(data) != size or _blob_sha(data) != sha:
                raise GitHubError('GitHub 批量文件内容校验失败')
            result[sha] = data
        return result

    def blobs(self, repo, entries):
        repo = self._repo(repo)
        wanted = {}
        for count, entry in enumerate(entries, 1):
            if count > 200_000 or not isinstance(entry, dict):
                raise GitHubError('GitHub 文件清单无效或超过允许条目数')
            sha = _sha(entry.get('sha'))
            size = entry.get('size')
            self._file_path(entry.get('path'))
            if ((size is not None and (type(size) is not int or not 0 <= size <= MAX_BLOB))
                    or entry.get('type', 'blob') != 'blob'
                    or entry.get('mode', '100644') not in ('100644', '100755')):
                raise GitHubError('GitHub 文件大小或类型不受支持')
            if sha in wanted and wanted[sha] is not None and size is not None and wanted[sha] != size:
                raise GitHubError('GitHub 相同文件标识的大小不一致')
            if sha not in wanted or size is not None:
                wanted[sha] = size
        if sum(size for size in wanted.values() if size is not None) > MAX_BLOBS_TOTAL:
            raise GitHubError('GitHub 去重文件总量超过 1 GiB，已停止读取')
        result = {}
        missing = []
        for sha, size in wanted.items():
            data = self._cached(sha, size)
            if data is None:
                missing.append((sha, size))
            else:
                result[sha] = data
                wanted[sha] = len(data)
                if sum(value for value in wanted.values() if value is not None) > MAX_BLOBS_TOTAL:
                    raise GitHubError('GitHub 去重文件总量超过 1 GiB，已停止读取')
        unknown = [(sha, size) for sha, size in missing if size is None]
        for offset in range(0, len(unknown), 50):
            batch = unknown[offset:offset + 50]
            values = self._graphql_blobs(repo, batch, text=False)
            for (sha, _), value in zip(batch, values):
                wanted[sha] = value['byteSize']
            if sum(size for size in wanted.values() if size is not None) > MAX_BLOBS_TOTAL:
                raise GitHubError('GitHub 去重文件总量超过 1 GiB，已停止读取')
        missing = [(sha, wanted[sha]) for sha, _ in missing]
        if sum(wanted.values()) > MAX_BLOBS_TOTAL:
            raise GitHubError('GitHub 去重文件总量超过 1 GiB，已停止读取')
        small = [(sha, size) for sha, size in missing if size <= SMALL_BLOB]
        # JSON escaping may expand text sixfold. Limit aggregate bytes as well
        # as object count so fifty individually small blobs cannot overflow JSON.
        batches = []
        current = []
        byte_count = 0
        for item in small:
            if current and (len(current) == 50 or byte_count + item[1] > MAX_JSON // 8):
                batches.append(current)
                current = []
                byte_count = 0
            current.append(item)
            byte_count += item[1]
        if current:
            batches.append(current)
        for items in batches:
            batch = self._small_blobs(repo, items)
            for sha, data in batch.items():
                self._save(sha, data)
                result[sha] = data
            self.progress(len(result), '正在读取 GitHub 投稿记录并校验内容')
        for sha, size in missing:
            if size > SMALL_BLOB:
                data = self._raw_blob(repo, sha, size)
                self._save(sha, data)
                result[sha] = data
                self.progress(len(result), '正在读取 GitHub 投稿记录并校验内容')
        return result
