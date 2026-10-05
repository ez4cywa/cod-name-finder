"""Version compatibility at the capture/offline boundary, without game processes."""
from copy import deepcopy
import json
import io
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

from finder import cordycep
from finder.snapshot import read_snapshot
from finder.store import Store


OLD_LOADER_SHA = 'fe43506a599fd84472c81599ace976b6ee6cde8b545745ea7ff0e3046fe1e1e7'
CURRENT_LOADER_SHA = 'a3a700bd4080f1d3eb7ee7084e0f42abc597c33f5a6eeded154105239f43b6f9'


def registry_data():
    return json.loads(Path(cordycep.__file__).with_name('cordycep_profiles.json').read_text(encoding='utf-8'))


def fake_installed_build(monkeypatch, root, game, loader_sha):
    """Hashes stand in for local binary contents; no actual loader is accessed."""
    profile = cordycep._profiles(game)
    reader = SimpleNamespace(pid=321, created=1000, image=root / 'Cordycep.CLI.exe')
    state = {'game_id': profile['game_ids'][0], 'flags': ['beta'] if game == 'COD2026' else [],
             'game_module_path': str((root / profile['module']).resolve())}
    hashes = {reader.image.resolve(): loader_sha,
              (root / 'Data/Configs' / profile['config']).resolve(): profile['config_sha256'],
              (root / profile['module']).resolve(): profile['module_sha256']}
    monkeypatch.setattr(cordycep, '_fingerprint_file', lambda path: hashes[Path(path).resolve()])
    return profile, reader, state, hashes


def replace_registry(monkeypatch, data):
    path = Path(cordycep.__file__).with_name('cordycep_profiles.json')
    original = Path.read_text
    def read_text(self, *args, **kwargs):
        return json.dumps(data) if self == path else original(self, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', read_text)


@pytest.mark.parametrize('game', ['COD2026', 'BO7'])
@pytest.mark.parametrize('loader_sha', [OLD_LOADER_SHA, CURRENT_LOADER_SHA])
def test_verified_old_and_current_loader_builds_keep_game_binding(tmp_path, monkeypatch, game, loader_sha):
    profile, reader, state, _ = fake_installed_build(monkeypatch, tmp_path, game, loader_sha)
    assert cordycep.validate_local_build(tmp_path, game, state, reader) == profile


@pytest.mark.parametrize('game', ['COD2026', 'BO7'])
def test_unknown_loader_hash_is_rejected_even_with_matching_game_files(tmp_path, monkeypatch, game):
    _, reader, state, _ = fake_installed_build(monkeypatch, tmp_path, game, '0' * 64)
    with pytest.raises(ValueError):
        cordycep.validate_local_build(tmp_path, game, state, reader)


@pytest.mark.parametrize('game', ['COD2026', 'BO7'])
@pytest.mark.parametrize('loader_sha', [OLD_LOADER_SHA, CURRENT_LOADER_SHA])
@pytest.mark.parametrize('changed', ['config_sha256', 'module_sha256'])
def test_each_loader_build_remains_bound_to_the_exact_game_files(tmp_path, monkeypatch, game, loader_sha, changed):
    profile, reader, state, hashes = fake_installed_build(monkeypatch, tmp_path, game, loader_sha)
    path = tmp_path / ('Data/Configs/' + profile['config'] if changed == 'config_sha256' else profile['module'])
    hashes[path.resolve()] = '0' * 64
    with pytest.raises(ValueError):
        cordycep.validate_local_build(tmp_path, game, state, reader)


@pytest.mark.parametrize('changed', ['config_sha256', 'module_sha256', 'wrong_game', 'adapter', 'filename', 'layout'])
def test_hash_allowlisting_alone_cannot_certify_an_incompatible_adapter(tmp_path, monkeypatch, changed):
    _, reader, state, _ = fake_installed_build(monkeypatch, tmp_path, 'COD2026', CURRENT_LOADER_SHA)
    data = registry_data()
    build = next(item for item in data['loader_builds'] if item['sha256'] == CURRENT_LOADER_SHA)
    if changed in ('config_sha256', 'module_sha256'):
        build['games']['COD2026'][changed] = '0' * 64
    elif changed == 'wrong_game':
        del build['games']['COD2026']
    elif changed == 'layout':
        data['layout']['id'] = 'unsupported-state-and-pool-layout'
    elif changed == 'adapter':
        build['adapter'] = 'unsupported-state-and-pool-layout'
    else:
        build['filename'] = 'other-loader.exe'
    replace_registry(monkeypatch, data)
    with pytest.raises(ValueError):
        cordycep.validate_local_build(tmp_path, 'COD2026', state, reader)


def test_single_loader_registry_from_previous_release_remains_accepted(tmp_path, monkeypatch):
    profile, reader, state, _ = fake_installed_build(monkeypatch, tmp_path, 'COD2026', OLD_LOADER_SHA)
    data = registry_data()
    data.pop('loader_builds', None)
    data.pop('preferred_loader_sha256', None)
    replace_registry(monkeypatch, data)
    assert cordycep.validate_local_build(tmp_path, 'COD2026', state, reader) == profile


@pytest.mark.parametrize('malformed', [[], None, 'invalid', 42, {'pid': 321},
                                     {'pid': 321, 'game_id': 'MODWAR7', 'pools_addr': 1, 'strings_addr': 0x400000}])
def test_malformed_state_is_a_recoverable_capture_error(tmp_path, malformed):
    (tmp_path / 'Data').mkdir()
    path = tmp_path / 'Data/CurrentHandler.json'
    path.write_text(json.dumps(malformed), encoding='utf-8')
    reader = SimpleNamespace(pid=321, created=1000, image=tmp_path / 'Cordycep.CLI.exe')
    with pytest.raises(ValueError):
        cordycep.handler_state(tmp_path, reader)


def test_unrecognized_attached_loader_is_rejected_before_pool_reads_and_is_never_owned(tmp_path, monkeypatch):
    _, reader, state, _ = fake_installed_build(monkeypatch, tmp_path, 'COD2026', '0' * 64)
    state.update(pid=321, pools_addr=0x100000, strings_addr=0x400000)
    closed = []
    class AttachedReader:
        image = reader.image
        def __init__(self, *args):
            self.pid = 321
        def __enter__(self):
            return self
        def __exit__(self, *args):
            closed.append(self.pid)
        def read(self, *args):
            raise AssertionError('an unknown build must not reach any pool address')
    def forbidden(*args, **kwargs):
        raise AssertionError('an attached user loader must not be started or managed')
    monkeypatch.setattr(cordycep, 'MemoryReader', AttachedReader)
    monkeypatch.setattr(cordycep, 'discover', lambda *args: {'instances': [{'pid': 321, 'game_id': 'MODWAR7'}]})
    monkeypatch.setattr(cordycep, 'handler_state', lambda *args: dict(state))
    monkeypatch.setattr(cordycep, 'LoaderSession', forbidden)
    monkeypatch.setattr(cordycep.subprocess, 'Popen', forbidden)
    with pytest.raises(ValueError):
        cordycep.capture(tmp_path, 'COD2026', tmp_path / 'output', pid=321)
    assert closed == [321]
    assert not (tmp_path / 'output').exists()


def test_current_build_capture_records_provenance_and_remains_portable(tmp_path, monkeypatch):
    _, reader, state, _ = fake_installed_build(monkeypatch, tmp_path, 'COD2026', CURRENT_LOADER_SHA)
    state.update(pid=321, pools_addr=0x100000, strings_addr=0x400000)
    class AttachedReader:
        image = reader.image
        def __init__(self, *args):
            self.pid = 321
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self, address, size):
            assert address == 0x100000 and size == 512 * 40
            return bytes(size)
    def forbidden(*args, **kwargs):
        raise AssertionError('a validated attached user loader must not be managed')
    monkeypatch.setattr(cordycep, 'MemoryReader', AttachedReader)
    monkeypatch.setattr(cordycep, 'discover', lambda *args: {'instances': [{'pid': 321, 'game_id': 'MODWAR7'}]})
    monkeypatch.setattr(cordycep, 'handler_state', lambda *args: dict(state))
    monkeypatch.setattr(cordycep, 'walk_pool', lambda reader, address, pool, control: ({(1 << 63) | 17} if pool == 6 else set(), 'stable'))
    monkeypatch.setattr(cordycep, 'read_strings', lambda *args, **kwargs: ({'weapon_name'}, {'bytes': 100, 'complete': True}))
    monkeypatch.setattr(cordycep, 'LoaderSession', forbidden)
    monkeypatch.setattr(cordycep.subprocess, 'Popen', forbidden)
    result = cordycep.capture(tmp_path, 'COD2026', tmp_path / 'output', pid=321)
    assert result['complete']
    metadata = json.loads(Path(result['snapshot_file']).read_text(encoding='utf-8'))
    build = next(item for item in registry_data()['loader_builds'] if item['sha256'] == CURRENT_LOADER_SHA)
    assert metadata['loader']['sha256'] == CURRENT_LOADER_SHA
    assert metadata['loader']['file_version'] == build['file_version']
    assert metadata['loader']['adapter'] == build['adapter']
    assert read_snapshot(result['snapshot_file'])['records'] == [((1 << 63) | 17, 6)]


def portable_capture(root):
    """Keep the established CODSNAP2 contract from the 2.2.0 release."""
    profile = deepcopy(cordycep._profiles('COD2026'))
    pools = {int(number): {**row, 'count': 0, 'stable': True, 'errors': []}
             for number, row in profile['pools'].items()}
    pools[6]['count'] = 1
    state = {'pid': 321, 'game_id': 'MODWAR7', '_capture_state_stable': True,
             'executable': 'D:/unavailable/Cordycep/Cordycep.CLI.exe'}
    result = cordycep._write_snapshot(root, 'COD2026', state, profile, pools,
                                    {((1 << 63) | 17, 6)}, {'weapon_name'},
                                    {'bytes': 100, 'complete': True}, True,
                                    'fixture supported scope stable', ['loaded fixture.ff'])
    path = Path(result['snapshot_file'])
    # A release 2.2.0 snapshot did not need a loader build fingerprint.
    metadata = json.loads(path.read_text(encoding='utf-8'))
    metadata['loader'] = {'executable': state['executable']}
    path.write_text(json.dumps(metadata), encoding='utf-8')
    return path


def test_previous_snapshot_is_portable_without_loader_or_research_files(tmp_path, monkeypatch):
    source = portable_capture(tmp_path / 'source')
    before = read_snapshot(source)
    relocated = tmp_path / 'new computer'
    relocated.mkdir()
    for name in ('snapshot.json', 'records.csv', 'strings.txt'):
        shutil.copy2(source.parent / name, relocated / name)
    shutil.rmtree(source.parent)

    def unavailable(*args, **kwargs):
        raise AssertionError('offline snapshot must not access a loader or process memory')
    monkeypatch.setattr(cordycep, '_kernel', unavailable)
    monkeypatch.setattr(cordycep, 'MemoryReader', unavailable)
    monkeypatch.setattr(cordycep, '_fingerprint_file', unavailable)
    after = read_snapshot(relocated)
    assert after['fingerprint'] == before['fingerprint']
    assert after['records'] == [((1 << 63) | 17, 6)]
    store = Store(tmp_path / 'work.sqlite')
    try:
        report = store.import_snapshot(relocated, 'COD2026', 'iw-resource63', kinds=('xanim',))
        assert report['unique_assets'] == 1
        assert store.db.execute('SELECT raw_hash FROM snapshot_records').fetchone()[0] == '8000000000000011'
    finally:
        store.close()


def test_loader_provenance_cannot_reclassify_a_portable_snapshot(tmp_path):
    path = portable_capture(tmp_path / 'source')
    before = read_snapshot(path)
    metadata = json.loads(path.read_text(encoding='utf-8'))
    metadata['loader'].update(sha256='0' * 64, file_version='unknown future loader')
    path.write_text(json.dumps(metadata), encoding='utf-8')
    # The independently verified game build/pool mapping remains authoritative.
    after = read_snapshot(path)
    assert after['fingerprint'] == before['fingerprint']
    assert after['pools'][6]['kind'] == 'xanim'


@pytest.mark.parametrize('field', ['module_sha256', 'config_sha256'])
def test_loader_provenance_does_not_override_wrong_offline_game_build(tmp_path, field):
    path = portable_capture(tmp_path / 'source')
    metadata = json.loads(path.read_text(encoding='utf-8'))
    metadata['loader'].update(sha256=OLD_LOADER_SHA, file_version='2.9.0.0')
    metadata['build_fingerprints'][field] = '0' * 64
    path.write_text(json.dumps(metadata), encoding='utf-8')
    with pytest.raises(ValueError, match='build SHA256'):
        read_snapshot(path)


class RecordedPipe(io.BytesIO):
    def __init__(self):
        super().__init__()
        self.writes = []
    def write(self, data):
        self.writes.append(data)
        return super().write(data)


class BatchChild:
    """An owned command Job; the CLI is PID 321, not this command PID."""
    pid = 900
    def __init__(self, owned=(321,), timeout=False):
        self.returncode = None
        self.stdin = RecordedPipe()
        self.stdout = io.BytesIO(b'loading\r\n\x1b[32mCordycep > \x1b[0m')
        self.owned = set(owned)
        self.ownership_checks = []
        self.timeout = timeout
        self.terminated = False
        self.close_calls = 0
    def poll(self):
        return self.returncode
    def owns(self, pid):
        self.ownership_checks.append(pid)
        return pid in self.owned
    def has_live_processes(self):
        return bool(self.owned)
    def wait(self, timeout):
        if self.timeout and not self.terminated:
            raise subprocess.TimeoutExpired('owned dummy batch', timeout)
        self.returncode = 0
        return 0
    def terminate(self):
        self.terminated = True
    def close(self):
        self.close_calls += 1


def mock_selected_batch(monkeypatch, child, instances):
    calls = []
    def owned_process(directory, script):
        calls.append((Path(directory), script))
        return child
    monkeypatch.setitem(sys.modules, 'finder.batch_loader', SimpleNamespace(OwnedBatchProcess=owned_process))
    monkeypatch.setattr(cordycep, 'discover', lambda *args: {'instances': instances})
    def forbidden(*args, **kwargs):
        raise AssertionError('selected BAT must execute through its owned Job, without legacy argument reconstruction')
    monkeypatch.setattr(cordycep, 'launch_arguments', forbidden)
    monkeypatch.setattr(cordycep.subprocess, 'Popen', forbidden)
    return calls


@pytest.mark.parametrize('game,game_id', [('COD2026', 'MODWAR7'), ('BO7', 'BLACKOP7')])
def test_selected_batch_preserves_unicode_spaces_ansi_prompt_and_actual_cli_pid(tmp_path, monkeypatch, game, game_id):
    child = BatchChild()
    script = '自定义 启动流程 中文.bat'
    calls = mock_selected_batch(monkeypatch, child, [
        {'pid': 777, 'game_id': game_id},  # This preexisting process is not in our Job.
        {'pid': 321, 'game_id': game_id}])
    session = cordycep.LoaderSession(tmp_path, game, lambda *args: None, lambda: 'run', script=script)
    try:
        assert session.start(timeout=1) == 321
        assert session.pid != child.pid
        assert calls == [(tmp_path, script)]
        assert 777 in child.ownership_checks and 321 in child.ownership_checks
        assert b'\x1b[32mCordycep > ' in session.output_tail
        assert child.stdin.writes == []
    finally:
        session.close()
    assert child.stdin.writes == [b'exit\r\n']
    assert child.close_calls == 1


@pytest.mark.parametrize('instances,owned', [
    ([{'pid': 321, 'game_id': 'BLACKOP7'}], (321,)),
    ([{'pid': 777, 'game_id': 'MODWAR7'}], (321,)),
    ([{'pid': 321, 'game_id': 'MODWAR7'}, {'pid': 322, 'game_id': 'MODWAR7'}], (321, 322))])
def test_batch_rejects_wrong_game_nonowned_or_ambiguous_pid_before_loadall(tmp_path, monkeypatch, instances, owned):
    child = BatchChild(owned)
    mock_selected_batch(monkeypatch, child, instances)
    session = cordycep.LoaderSession(tmp_path, 'COD2026', lambda *args: None, lambda: 'run', script='选择.bat')
    prompt_checks = []
    monkeypatch.setattr(session, '_wait_prompt', lambda timeout: prompt_checks.append(timeout))
    try:
        with pytest.raises(ValueError):
            session.start(load_all=True, timeout=1)
        assert child.stdin.writes == []
        assert prompt_checks == [1]
    finally:
        session.close()
    assert child.close_calls == 1


def test_initializing_existing_cli_prevents_starting_any_selected_batch(tmp_path, monkeypatch):
    class InitializingReader:
        image = tmp_path / 'Cordycep.CLI.exe'
        def __init__(self, *args):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
    def forbidden(*args, **kwargs):
        raise AssertionError('an existing initializing CLI must block startup without requiring JSON state')
    monkeypatch.setattr(cordycep, 'process_ids', lambda: [888])
    monkeypatch.setattr(cordycep, 'MemoryReader', InitializingReader)
    monkeypatch.setattr(cordycep, 'handler_state', forbidden)
    monkeypatch.setattr(cordycep, 'LoaderSession', forbidden)
    assert cordycep.directory_running(tmp_path)
    with pytest.raises(ValueError, match='已有加载器'):
        cordycep.capture(tmp_path, 'COD2026', tmp_path / 'output', launch=True, script='自定义启动.bat')
    assert not (tmp_path / 'output').exists()


def test_attaching_an_existing_loader_never_accepts_a_batch_to_execute(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('a BAT supplied in attach mode must be refused before looking up a process')
    monkeypatch.setattr(cordycep, 'discover', forbidden)
    monkeypatch.setattr(cordycep, 'LoaderSession', forbidden)
    with pytest.raises(ValueError, match='启动模式'):
        cordycep.capture(tmp_path, 'COD2026', tmp_path / 'output', pid=321, script='启动.bat')


def test_failed_selected_batch_capture_releases_its_job_without_a_snapshot(tmp_path, monkeypatch):
    child = BatchChild()
    mock_selected_batch(monkeypatch, child, [{'pid': 321, 'game_id': 'BLACKOP7'}])
    monkeypatch.setattr(cordycep, 'directory_running', lambda directory: False)
    with pytest.raises(ValueError, match='匹配作品'):
        cordycep.capture(tmp_path, 'COD2026', tmp_path / 'output', launch=True, load_all=True, script='选择 BO7.bat')
    assert child.stdin.writes == [b'exit\r\n']
    assert child.close_calls == 1
    assert not child.terminated
    assert not (tmp_path / 'output').exists()


@pytest.mark.parametrize('timeout', [False, True])
def test_batch_session_close_releases_only_the_helper_owned_job(tmp_path, monkeypatch, timeout):
    child = BatchChild(timeout=timeout)
    calls = mock_selected_batch(monkeypatch, child, [{'pid': 321, 'game_id': 'MODWAR7'}])
    session = cordycep.LoaderSession(tmp_path, 'COD2026', lambda *args: None, lambda: 'run', script='启动.bat')
    assert session.start(timeout=1) == 321
    session.close()
    assert len(calls) == 1
    assert child.stdin.writes == [b'exit\r\n']
    assert child.terminated is timeout
    assert child.stdin.closed and child.stdout.closed
    assert child.close_calls == 1


def test_startup_scripts_lists_only_root_batch_files_with_exact_names(tmp_path):
    for name in ('RunMW7Beta.bat', '自定义 启动.BAT', 'notes.txt', 'Cordycep.CLI.exe'):
        (tmp_path / name).write_text('fixture', encoding='utf-8')
    child = tmp_path / 'other files'
    child.mkdir()
    (child / 'nested.bat').write_text('fixture', encoding='utf-8')
    assert cordycep.startup_scripts(tmp_path)['scripts'] == ['RunMW7Beta.bat', '自定义 启动.BAT']


def test_batch_cmd_can_exit_while_owned_matching_loader_returns_its_prompt(tmp_path, monkeypatch):
    child = BatchChild()
    child.returncode = 0
    mock_selected_batch(monkeypatch, child, [{'pid': 321, 'game_id': 'MODWAR7'}])
    session = cordycep.LoaderSession(tmp_path, 'COD2026', lambda *args: None, lambda: 'run', script='后台启动.bat')
    try:
        assert session.start(timeout=1) == 321
        assert session.pid != child.pid
        assert b'Cordycep > ' in session.output_tail
        assert child.stdin.writes == []
    finally:
        session.close()
    # CMD has exited; releasing its Job still cleans up its owned loader.
    assert child.close_calls == 1
    assert child.stdin.writes == []


def test_batch_cmd_exit_without_owned_processes_cannot_confirm_even_a_queued_prompt(tmp_path, monkeypatch):
    child = BatchChild(owned=())
    child.returncode = 0
    mock_selected_batch(monkeypatch, child, [{'pid': 321, 'game_id': 'MODWAR7'}])
    session = cordycep.LoaderSession(tmp_path, 'COD2026', lambda *args: None, lambda: 'run', script='已退出.bat')
    try:
        with pytest.raises(ValueError, match='加载完成前退出'):
            session.start(timeout=1)
        assert not child.ownership_checks
    finally:
        session.close()
    assert child.close_calls == 1


@pytest.mark.parametrize('root_code', [None, 0])
def test_batch_capture_stdout_eof_never_certifies_loading_or_writes_snapshot(tmp_path, monkeypatch, root_code):
    child = BatchChild()
    child.returncode = root_code
    child.stdout = io.BytesIO(b'initializing game, without a completion prompt\r\n')
    mock_selected_batch(monkeypatch, child, [{'pid': 321, 'game_id': 'MODWAR7'}])
    monkeypatch.setattr(cordycep, 'directory_running', lambda directory: False)
    with pytest.raises(ValueError, match='没有返回可核对的完成提示'):
        cordycep.capture(tmp_path, 'COD2026', tmp_path / 'output', launch=True, script='没有提示.bat')
    assert child.close_calls == 1
    assert child.stdin.closed and child.stdout.closed
    assert not (tmp_path / 'output').exists()
    assert child.stdin.writes == ([b'exit\r\n'] if root_code is None else [])


def test_capture_entry_executes_the_selected_batch_and_reads_the_owned_cli_pid(tmp_path, monkeypatch):
    _, reader, state, _ = fake_installed_build(monkeypatch, tmp_path, 'COD2026', CURRENT_LOADER_SHA)
    state.update(pid=321, pools_addr=0x100000, strings_addr=0x400000)
    child = BatchChild()
    child.returncode = 0
    script = '自定义 后台流程.bat'
    calls = mock_selected_batch(monkeypatch, child, [{'pid': 321, 'game_id': 'MODWAR7'}])
    opened = []
    class AttachedReader:
        image = reader.image
        def __init__(self, pid, directory):
            assert pid == 321
            opened.append(pid)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self, address, size):
            assert address == 0x100000 and size == 512 * 40
            return bytes(size)
    monkeypatch.setattr(cordycep, 'directory_running', lambda directory: False)
    monkeypatch.setattr(cordycep, 'MemoryReader', AttachedReader)
    monkeypatch.setattr(cordycep, 'handler_state', lambda *args: dict(state))
    monkeypatch.setattr(cordycep, 'walk_pool', lambda reader, address, pool, control: ({17} if pool == 6 else set(), 'stable'))
    monkeypatch.setattr(cordycep, 'read_strings', lambda *args, **kwargs: ({'weapon_name'}, {'bytes': 100, 'complete': True}))
    result = cordycep.capture(tmp_path, 'COD2026', tmp_path / 'output', launch=True, script=script)
    assert result['complete'] and result['pid'] == 321
    assert calls == [(tmp_path, script)] and opened == [321]
    assert child.close_calls == 1
    metadata = json.loads(Path(result['snapshot_file']).read_text(encoding='utf-8'))
    assert metadata['loader']['startup_script'] == str(tmp_path / script)
    assert read_snapshot(result['snapshot_file'])['records'] == [(17, 6)]
