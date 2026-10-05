"""Explicit opt-in live BAT integration check against the packaged application.

Requires a local compatible Cordycep, its configured game and the user's normal
startup requirements. It runs the specified BAT once, through the GUI worker;
it never copies game or authorization files. Not part of fixture-only tests.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--script', required=True)
    parser.add_argument('--game', choices=['COD2026', 'BO7'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    app = args.app.resolve(strict=True)
    directory = args.directory.resolve(strict=True)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    for key in ('PYTHONHOME', 'PYTHONPATH', 'COD_NAME_FINDER_ENGINE'):
        environment.pop(key, None)
    environment['PATH'] = str(Path(environment.get('SystemRoot', r'C:\Windows')) / 'System32')
    environment['DOTNET_ROOT'] = str(output / 'no-system-dotnet')
    environment['DOTNET_ROOT_X64'] = environment['DOTNET_ROOT']
    environment['DOTNET_MULTILEVEL_LOOKUP'] = '0'
    command = [str(app), 'gui-capture', str(directory), '--game', args.game,
        '--output', str(output), '--launch', '--script', args.script, '--validation']
    completed = subprocess.run(command, cwd=output, env=environment,
        capture_output=True, encoding='utf-8', errors='strict', timeout=180,
        creationflags=subprocess.CREATE_NO_WINDOW)
    (output / 'gui-capture.jsonl').write_text(completed.stdout, encoding='utf-8')
    assert completed.returncode == 0, completed.stderr + completed.stdout[-2000:]
    rows = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
    state = next(row for row in rows if row['event'] == 'gui_validation')
    result = next(row['result'] for row in rows if row['event'] == 'result')
    assert state['native_aot'] and state['bat_dropdown']
    assert state['selected_script'] == args.script and state['bat_count'] > 0
    assert result['complete'] and result['status'] == 'completed'
    assert state['input_mode'] == 'snapshot' and state['snapshot_file'] == result['snapshot_file']
    snapshot = Path(result['snapshot_file'])
    manifest = json.loads(snapshot.read_text(encoding='utf-8'))
    assert manifest['complete'] and manifest['state_stable']
    assert Path(manifest['loader']['startup_script']) == directory / args.script
    loader = directory / 'Cordycep.CLI.exe'
    assert manifest['loader']['sha256'] == hashlib.sha256(loader.read_bytes()).hexdigest()
    for field in ('records', 'strings'):
        metadata = manifest[field]
        assert hashlib.sha256((snapshot.parent / metadata['file']).read_bytes()).hexdigest() == metadata['sha256']
    verified_pools = set(manifest['verified_scope_pools'])
    assert len(verified_pools) == 16
    assert all(pool['stable'] and not pool['errors'] for pool in manifest['pools'] if pool['pool'] in verified_pools)
    report = {'passed': True, 'live_cordycep': True, 'protocol_stub': False,
        'native_aot': True, 'system32_only_path': True, 'no_system_python_or_dotnet': True,
        'selected_bat': args.script, 'bat_count': state['bat_count'],
        'loader_sha256': manifest['loader']['sha256'], 'game': args.game,
        'capture': result, 'snapshot_auto_selected': True,
        'verified_pool_count': len(verified_pools),
        'scope': 'Current BAT loaded set, not asserted the whole game'}
    (output / 'validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
