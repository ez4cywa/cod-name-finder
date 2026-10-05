"""Real CLI process regressions for Windows UTF-8 errors and exit status."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from finder.candidates import Plan
from finder.engine import create_task
from finder.formats import encode_cdb
from finder.hashing import PROFILES
from finder.store import Store

ROOT = Path(__file__).resolve().parents[1]


def invoke(args, entrypoint='module'):
    command = [sys.executable, '-m', 'finder'] if entrypoint == 'module' else [sys.executable, str(ROOT / 'launch.py')]
    environment = os.environ.copy()
    # A Chinese Windows legacy encoding must not corrupt the worker protocol.
    environment['PYTHONIOENCODING'] = 'gbk'
    environment['PYTHONUTF8'] = '0'
    result = subprocess.run(command + list(map(str, args)), cwd=ROOT, env=environment,
                            capture_output=True, timeout=30)
    stdout = result.stdout.decode('utf-8')
    stderr = result.stderr.decode('utf-8')
    assert '\ufffd' not in stdout + stderr
    assert 'Traceback' not in stdout + stderr
    assert 'Failed to execute script' not in stdout + stderr
    return result.returncode, stdout, stderr


def configuration(tmp_path):
    folder = tmp_path / '空哈希文件夹'
    folder.mkdir()
    indexes = tmp_path / '名称索引'
    indexes.mkdir()
    (indexes / 'fnv1a_xanims.cdb').write_bytes(encode_cdb({1: 'jup_mp_strafe_walk_1'}))
    value = {'folder': str(folder), 'indexes': str(indexes), 'output': str(tmp_path / '结果'),
             'asset_type': 'xanim', 'backend': 'cpu', 'budget': 1000, 'seconds': 30}
    path = tmp_path / '中文配置.json'
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    return path, value


def error_event(stdout):
    events = [json.loads(line) for line in stdout.splitlines() if line.strip()]
    assert events and events[-1]['event'] == 'error'
    assert sum(event.get('event') == 'error' for event in events) == 1
    assert not any(event.get('event') == 'result' for event in events)
    error = events[-1]
    assert error['type'] and error['message']
    return error


@pytest.mark.parametrize('entrypoint', ['module', 'launch'])
def test_empty_directory_error_is_utf8_structured_and_identifies_real_input(tmp_path, entrypoint):
    path, value = configuration(tmp_path)
    code, stdout, stderr = invoke(['run', path], entrypoint)
    assert code == 2 and stderr == ''
    error = error_event(stdout)
    assert error['type'] == 'ValueError' and '资产' in error['message']
    assert error['command'] == 'run'
    assert error['config_file'] == str(path.resolve())
    assert error['input_folder'] == str(Path(value['folder']).resolve())
    assert '空哈希文件夹' in stdout


@pytest.mark.parametrize('entrypoint', ['module', 'launch'])
def test_missing_chinese_config_has_nonzero_status_without_uncaught_trace(tmp_path, entrypoint):
    path = tmp_path / '不存在的配置.json'
    code, stdout, stderr = invoke(['run', path], entrypoint)
    assert code == 2 and stderr == ''
    error = error_event(stdout)
    assert error['type'] == 'FileNotFoundError'
    assert error['config_file'] == str(path.resolve())
    assert '不存在的配置.json' in error['message']


@pytest.mark.parametrize('entrypoint', ['module', 'launch'])
def test_bad_json_reports_human_chinese_message(tmp_path, entrypoint):
    path = tmp_path / '损坏配置.json'
    path.write_text('{"folder":', encoding='utf-8')
    code, stdout, stderr = invoke(['run', path], entrypoint)
    assert code == 2 and stderr == ''
    error = error_event(stdout)
    assert error['type'] == 'JSONDecodeError'
    assert '配置文件不是有效 JSON' in error['message']
    assert error['config_file'] == str(path.resolve())


def test_non_object_configuration_is_a_readable_input_error(tmp_path):
    path = tmp_path / '数组配置.json'
    path.write_text('[]', encoding='utf-8')
    code, stdout, stderr = invoke(['run', path])
    assert code == 2 and stderr == ''
    error = error_event(stdout)
    assert error['type'] == 'ValueError' and 'JSON 对象' in error['message']


def test_invalid_profile_error_preserves_original_chinese(tmp_path):
    path, value = configuration(tmp_path)
    value['profile'] = 'not-an-algorithm'
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    code, stdout, stderr = invoke(['run', path])
    assert code == 2 and stderr == ''
    assert error_event(stdout)['message'] == '请选择正确的哈希规则'


def test_stdout_result_protocol_and_successful_launch_exit_remain_compatible(tmp_path):
    path, value = configuration(tmp_path)
    profile = PROFILES['iw-resource63']
    name = 'rex_mp_strafe_walk_1'
    (Path(value['folder']) / f'anim_{profile.digest(name):016x}.cast').write_bytes(b'fixture')
    code, stdout, stderr = invoke(['run', path], 'launch')
    assert code == 0 and stderr == ''
    events = [json.loads(line) for line in stdout.splitlines() if line.strip()]
    assert any(event['event'] == 'progress' for event in events)
    assert events[-1]['event'] == 'result'
    assert events[-1]['result']['status'] == 'completed'
    assert events[-1]['result']['entries'] == 1


def test_devices_and_utf8_argparse_stderr_remain_compatible():
    code, stdout, _ = invoke(['devices'])
    assert code == 0 and isinstance(json.loads(stdout), list)
    code, stdout, stderr = invoke(['devices', '--中文未知参数'])
    assert code == 2 and stdout == '' and '中文未知参数' in stderr


def test_worker_success_keeps_legacy_json_protocol(tmp_path):
    path, value = configuration(tmp_path)
    profile = PROFILES['iw-resource63']
    name = 'rex_mp_strafe_walk_1'
    (Path(value['folder']) / f'anim_{profile.digest(name):016x}.cast').write_bytes(b'fixture')
    database = tmp_path / '后台数据库.sqlite'
    store = Store(database)
    store.import_exported(value['folder'], 'worker-test', profile.id)
    task = create_task(store, Plan([[name]]), [profile.id], backend='cpu')
    store.close()
    control = tmp_path / '控制.txt'
    control.write_text('run', encoding='utf-8')
    code, stdout, stderr = invoke(['--work', database, 'worker', task, control])
    assert code == 0 and stderr == ''
    events = [json.loads(line) for line in stdout.splitlines() if line.strip()]
    assert any('position' in event and 'message' in event for event in events[:-1])
    assert events[-1]['status'] == 'completed'


def test_gui_job_displays_original_error_text_instead_of_json(tmp_path, monkeypatch):
    from finder.gui import Job
    _, value = configuration(tmp_path)
    monkeypatch.setenv('PYTHONIOENCODING', 'gbk')
    job = Job(value, None)
    failures = []
    successes = []
    job.failed.connect(failures.append)
    job.done.connect(successes.append)
    # Running the worker method directly exercises its real CLI subprocess and
    # signal payload without opening a window or requiring a GUI event loop.
    job.run()
    assert successes == [] and len(failures) == 1
    message = failures[0]
    assert '资产' in message and '哈希文件夹：' in message
    assert str(Path(value['folder']).resolve()) in message
    assert '\ufffd' not in message and 'Traceback' not in message
    assert '"event"' not in message and '"message"' not in message


def test_gui_job_success_uses_real_control_file_and_emits_one_new_name(tmp_path, monkeypatch):
    from finder import gui
    _, value = configuration(tmp_path)
    profile = PROFILES['iw-resource63']
    name = 'rex_mp_strafe_walk_1'
    (Path(value['folder']) / f'anim_{profile.digest(name):016x}.cast').write_bytes(b'fixture')
    original_popen = subprocess.Popen
    controls = []

    def recorded_popen(command, *args, **kwargs):
        assert '--control' in command
        control = Path(command[command.index('--control') + 1])
        assert control.is_file() and control.read_bytes() == b'run'
        controls.append(control)
        # Start the real CLI rather than a mock process: candidate execution
        # uses repeated control-file reads through the normal waiting path.
        return original_popen(command, *args, **kwargs)

    monkeypatch.setattr(gui.subprocess, 'Popen', recorded_popen)
    job = gui.Job(value, None)
    failures = []
    successes = []
    job.failed.connect(failures.append)
    job.done.connect(successes.append)
    job.run()
    assert len(controls) == 1 and failures == [] and len(successes) == 1
    assert successes[0]['status'] == 'completed' and successes[0]['entries'] == 1
    assert successes[0]['verified_target_matches'] == 1
    assert Path(successes[0]['new_names_csv']).is_file()
    assert job.control_path is None and not controls[0].exists()
