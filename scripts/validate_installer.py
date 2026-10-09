"""Verify the installed one-click release with an isolated validation AppId.

Run only after building this version's installer. Search commands use the
installed executable, a temporary working directory and a System32-only PATH,
without the research project, Python runtime or source-tree PYTHONPATH. An
additional GUI capture also checks the machine's unchanged normal environment.
"""
import hashlib
import csv
from contextlib import closing
import json
from io import BytesIO
import os
from pathlib import Path
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile
import threading
import time
import pefile
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from finder import VERSION
from finder.assets import ASSET_LABELS
from finder.exporter import SALUKI_PACKAGES
from finder.formats import decode_cdb, encode_cdb
from finder.hashing import PROFILES

ROOT = Path(__file__).resolve().parents[1]


def validate_glass_state(state, *, reduced=False, tutorial=False):
    """Require actual shader/capture/filter work, or a clean forced fallback."""
    assert state['style'] == 'liquid-glass'
    assert state['actions_visible'] is True
    assert state['input_viewport_height'] > 0
    assert 0 < state['log_height'] <= 72.1
    if not tutorial:
        assert state['compact_header'] and state['introduction_removed'] and state['custom_titlebar']
        assert 0 < state['titlebar_height'] <= 52
        assert state['window_buttons'] == ['最小化窗口', '最大化窗口', '关闭窗口']
    glass = state['glass']
    assert glass['style_reference'] == 'KaranocaVe/LiquidGlassAvaloniaUI'
    assert glass['backdrop_palette'] == 'blue-rose-amber-original-vector'
    assert glass['refraction_amount'] > glass['refraction_height'] > 0
    assert glass['chromatic_aberration'] and glass['depth_effect']
    assert glass['effects_enabled'] is (not reduced)
    assert glass['filter_failures'] == 0
    fields = ('validated_shaders', 'shader_panels', 'captures_published',
              'renderer_invalidations', 'filter_cache_misses', 'filter_cache_hits',
              'gpu_filter_surfaces', 'cpu_filter_surfaces', 'filter_failures')
    assert all(isinstance(glass[field], int) and glass[field] >= 0 for field in fields)
    if reduced:
        assert all(glass[field] == 0 for field in fields)
    else:
        assert glass['validated_shaders'] == 6
        assert glass['shader_panels'] == (2 if tutorial else 3)
        assert glass['captures_published'] > 0 and glass['renderer_invalidations'] > 0
        assert glass['filter_cache_misses'] > 0
        assert glass['gpu_filter_surfaces'] + glass['cpu_filter_surfaces'] > 0


def fingerprints(directory):
    """Include names and bytes so additions, removals and changes are detected."""
    return {
        p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(Path(directory).rglob('*')) if p.is_file()
    }


def pe_clr_directory(path):
    """Read the PE header directly, independently of runtime self-reporting."""
    blob = Path(path).read_bytes()
    assert blob[:2] == b'MZ', 'The published UI is not a Windows executable'
    pe_offset = struct.unpack_from('<I', blob, 0x3c)[0]
    assert blob[pe_offset:pe_offset + 4] == b'PE\0\0'
    assert struct.unpack_from('<H', blob, pe_offset + 4)[0] == 0x8664, 'Expected win-x64'
    optional_size = struct.unpack_from('<H', blob, pe_offset + 20)[0]
    optional = pe_offset + 24
    assert struct.unpack_from('<H', blob, optional)[0] == 0x20b, 'Expected PE32+'
    assert struct.unpack_from('<I', blob, optional + 108)[0] >= 15
    clr_offset = optional + 112 + 14 * 8
    assert clr_offset + 8 <= optional + optional_size
    return struct.unpack_from('<II', blob, clr_offset)


def validate_icon_payload(payload, width, height):
    """Validate the actual PNG/DIB image referenced by an icon directory."""
    assert len(payload) >= 16, 'An icon image is missing or truncated'
    if payload.startswith(b'\x89PNG\r\n\x1a\n'):
        with Image.open(BytesIO(payload)) as bitmap:
            assert bitmap.format == 'PNG' and bitmap.size == (width, height)
            bitmap.load()
    else:
        header_size = struct.unpack_from('<I', payload)[0]
        assert header_size in (40, 108, 124), 'The icon image is not a supported Windows DIB'
        assert len(payload) >= header_size
        dib_width, dib_height, planes, depth = struct.unpack_from('<iiHH', payload, 4)
        assert dib_width == width and abs(dib_height) == height * 2
        assert planes == 1 and depth in (1, 4, 8, 16, 24, 32)
        minimum_pixels = ((width * depth + 31) // 32) * 4 * height
        assert len(payload) >= header_size + minimum_pixels


def pe_icon_resources(path):
    """Require linked RT_GROUP_ICON/RT_ICON images in the published PE file."""
    with pefile.PE(str(path), fast_load=True) as executable:
        executable.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_RESOURCE']])
        assert hasattr(executable, 'DIRECTORY_ENTRY_RESOURCE'), f'No PE resources: {path}'
        resources = {}
        for resource_type in executable.DIRECTORY_ENTRY_RESOURCE.entries:
            if resource_type.id not in (3, 14): continue
            images = resources.setdefault(resource_type.id, {})
            for name_entry in resource_type.directory.entries:
                for language_entry in name_entry.directory.entries:
                    data = language_entry.data.struct
                    payload = executable.get_data(data.OffsetToData, data.Size)
                    assert len(payload) == data.Size
                    images.setdefault(name_entry.id, []).append(payload)
        assert resources.get(3) and resources.get(14), f'Actual icon resources are missing: {path}'
        sizes = set(); groups = 0; referenced = set()
        for payloads in resources[14].values():
            for group in payloads:
                reserved, kind, count = struct.unpack_from('<HHH', group)
                assert reserved == 0 and kind == 1 and count > 0
                assert len(group) == 6 + 14 * count
                groups += 1
                for index in range(count):
                    width, height, _, _, _, _, byte_count, icon_id = struct.unpack_from('<BBBBHHIH', group, 6 + index * 14)
                    width = width or 256; height = height or 256
                    linked = resources[3].get(icon_id, [])
                    assert linked, f'RT_GROUP_ICON references a missing RT_ICON {icon_id}: {path}'
                    matching = [image for image in linked if len(image) == byte_count]
                    assert matching, f'Icon resource length does not match its directory: {path}'
                    validate_icon_payload(matching[0], width, height)
                    sizes.add((width, height)); referenced.add(icon_id)
        return {'groups': groups, 'referenced_images': len(referenced),
                'sizes': [list(size) for size in sorted(sizes)]}


def installed_icon_assets(directory):
    ico = Path(directory) / 'assets/cod-name-finder.ico'
    png = Path(directory) / 'assets/cod-name-finder.png'
    assert ico.is_file() and png.is_file(), 'Installed icon source assets are missing'
    blob = ico.read_bytes()
    reserved, kind, count = struct.unpack_from('<HHH', blob)
    assert reserved == 0 and kind == 1 and count >= 7
    assert len(blob) >= 6 + count * 16
    sizes = set()
    for index in range(count):
        width, height, _, _, _, _, length, offset = struct.unpack_from('<BBBBHHII', blob, 6 + index * 16)
        width = width or 256; height = height or 256
        assert offset >= 6 + count * 16 and length > 0 and offset + length <= len(blob)
        validate_icon_payload(blob[offset:offset + length], width, height)
        sizes.add((width, height))
    assert {(16, 16), (32, 32), (48, 48), (256, 256)} <= sizes
    with Image.open(png) as bitmap:
        assert bitmap.format == 'PNG' and bitmap.mode == 'RGBA'
        bitmap.load()
        alpha = bitmap.getchannel('A'); extrema = alpha.getextrema()
        assert extrema == (0, 255), 'The PNG has no genuine transparent and opaque pixels'
        histogram = alpha.histogram()
        assert histogram[0] > 0 and histogram[255] > 0
        png_size = list(bitmap.size)
    return {'ico_frames': count, 'ico_sizes': [list(size) for size in sorted(sizes)],
            'png_mode': 'RGBA', 'png_size': png_size, 'transparent_pixels': histogram[0],
            'opaque_pixels': histogram[255], 'ico_sha256': hashlib.sha256(blob).hexdigest(),
            'png_sha256': hashlib.sha256(png.read_bytes()).hexdigest()}


def main():
    installer = ROOT / 'releases' / f'CODNameFinder-{VERSION}-Setup.exe'
    if not installer.is_file():
        raise FileNotFoundError(f'Build the installer before validation: {installer}')
    validation = ROOT / 'validation'
    validation.mkdir(exist_ok=True)
    report = {'version': VERSION, 'format': 'exe-installer',
              'installer_sha256': hashlib.sha256(installer.read_bytes()).hexdigest(),
              'commands': [], 'runs': []}
    with tempfile.TemporaryDirectory(prefix='finder-installer-') as temp:
        base = Path(temp)
        install = base / 'Installed App'
        env = os.environ.copy()
        for key in ('PYTHONHOME', 'PYTHONPATH', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH'):
            env.pop(key, None)
        env['PATH'] = str(Path(env.get('SystemRoot', env.get('SYSTEMROOT', r'C:\Windows'))) / 'System32')
        missing_dotnet = base / 'Nonexistent Dotnet Runtime'
        assert not missing_dotnet.exists()
        env['DOTNET_ROOT'] = str(missing_dotnet)
        env['DOTNET_ROOT_X64'] = str(missing_dotnet)
        env['DOTNET_MULTILEVEL_LOOKUP'] = '0'
        assert 'PYTHONPATH' not in env and 'PYTHONHOME' not in env

        def execute(executable, *args, environment=None):
            started = time.monotonic()
            command = [str(executable), *map(str, args)]
            completed = subprocess.run(
                command, cwd=base, env=env if environment is None else environment, capture_output=True, text=True,
                encoding='utf-8', errors='replace', timeout=120)
            entry = {'args': command, 'exit_code': completed.returncode,
                     'environment': 'system32-only' if environment is None else 'current',
                     'seconds': round(time.monotonic() - started, 3)}
            if environment is None:
                entry['dotnet_runtime_root'] = 'nonexistent'
            if completed.stderr.strip():
                entry['stderr_tail'] = completed.stderr[-4000:]
            report['commands'].append(entry)
            assert completed.returncode == 0, completed.stdout + completed.stderr
            return completed.stdout

        def expect_error(executable, *args):
            """Validate raw UTF-8 error bytes and the actual process exit code."""
            started = time.monotonic()
            command = [str(executable), *map(str, args)]
            error_environment = env.copy()
            error_environment['PYTHONIOENCODING'] = 'cp936'
            completed = subprocess.run(command, cwd=base, env=error_environment,
                                       capture_output=True, timeout=120)
            # Strict decoding catches a Chinese Windows-codepage error stream;
            # errors='replace' would conceal the original reported defect.
            stdout = completed.stdout.decode('utf-8')
            stderr = completed.stderr.decode('utf-8')
            report['commands'].append({'args': command, 'exit_code': completed.returncode,
                'environment': 'system32-only', 'inherited_pythonioencoding': 'cp936',
                'seconds': round(time.monotonic() - started, 3), 'expected_error': True,
                'stderr_tail': stderr[-4000:]})
            assert completed.returncode == 2, stdout + stderr
            assert 'Traceback' not in stdout + stderr and 'PYI' not in stdout + stderr
            events = [json.loads(line) for line in stdout.splitlines() if line.strip()]
            assert events and events[-1].get('event') == 'error', stdout + stderr
            assert not any(event.get('event') == 'result' for event in events)
            message = events[-1].get('message', '')
            assert any('\u4e00' <= character <= '\u9fff' for character in message), message
            assert '\ufffd' not in stdout + stderr
            return events[-1]

        exe = install / 'CODNameFinder.exe'
        engine = install / 'engine/NameFinder.Engine.exe'
        cdb_reader = install / 'engine/_internal/cdb-inspect.exe'
        work_files = []
        source_before = None
        try:
            execute(installer, '/VALIDATION', '/VERYSILENT', '/SUPPRESSMSGBOXES',
                    '/NORESTART', '/NOICONS', f'/DIR={install}',
                    f'/LOG={validation / ("install-" + VERSION + ".log")}')
            assert exe.is_file() and (install / 'docs/user-guide.zh-CN.md').is_file()
            assert engine.is_file() and cdb_reader.is_file(), 'The bundled calculation worker is missing'
            architecture = json.loads((install / 'architecture.json').read_text(encoding='utf-8'))
            assert architecture['version'] == VERSION and architecture['ui'].startswith('Avalonia ')
            assert architecture['ui_style'] == 'liquid-glass'
            assert architecture['glass_library'] == 'Fluid.Avalonia.Acrylic 1.4.0'
            assert architecture['glass_library_source_commit'] == '013590eaa93666d368d775efdb3d7715591a4232'
            assert architecture['glass_background'] == 'application-internal-skia-sampling'
            assert architecture['ui_compilation'] == 'dotnet-native-aot'
            assert architecture['target'] == 'win-x64' and architecture['backend'] == 'bundled-python'
            assert architecture['backend_executable'] == 'engine/NameFinder.Engine.exe'
            assert architecture['requires_system_python'] is False
            assert architecture['requires_system_dotnet'] is False
            assert architecture['protocol'] == 'utf8-json-lines'
            assert architecture['stop'] == 'control-file-pause-and-export'
            assert architecture['capture_launch'] == 'user-selected-local-bat-windows-owned-job'
            assert architecture['compatible_loader_builds'] == 2
            profiles = json.loads((install / 'engine/_internal/finder/cordycep_profiles.json').read_text(encoding='utf-8'))
            assert len(profiles['loader_builds']) == 2
            assert profiles['preferred_loader_sha256'] == 'a3a700bd4080f1d3eb7ee7084e0f42abc597c33f5a6eeded154105239f43b6f9'
            assert (install / 'engine/_internal/finder/batch_loader.py').is_file()
            assert (install / 'docs/cordycep-latest-research.zh-CN.md').is_file()
            report['selected_bat_and_latest_build_payload_verified'] = True
            fluid_license = (install / 'licenses/dotnet/Fluid.Avalonia.Acrylic/LICENSE').read_text(encoding='utf-8')
            assert 'MIT License' in fluid_license
            assert 'Copyright (c) 2025 KaranocaVe' in fluid_license
            assert 'Copyright (c) 2026 Alpaq92' in fluid_license
            assert (install / 'docs/liquid-glass-research.zh-CN.md').is_file()
            dotnet_lock = json.loads((install / 'licenses/dotnet-packages.lock.json').read_text(encoding='utf-8'))
            assert any(packages.get('Fluid.Avalonia.Acrylic', {}).get('resolved') == '1.4.0'
                       for packages in dotnet_lock['dependencies'].values())
            report['liquid_glass_library_license_verified'] = True
            assert pe_clr_directory(exe) == (0, 0), 'The UI still has a managed CLR header'
            assert list((install / 'engine/_internal').glob('python3*.dll')), 'Python runtime is not bundled'
            assert not any('pyside6' in p.name.lower() or 'qt6' in p.name.lower()
                           for p in install.rglob('*')), 'A legacy Qt/PySide6 dependency remains'
            report.update({'architecture': architecture, 'native_aot_pe_clr_directory_zero': True,
                'bundled_python_worker_verified': True, 'legacy_qt_removed_verified': True,
                'nonexistent_system_dotnet_root': str(missing_dotnet)})
            report['application_icon_resources'] = pe_icon_resources(exe)
            report['installer_icon_resources'] = pe_icon_resources(installer)
            report['installed_icon_assets'] = installed_icon_assets(install)
            report['exe_installer_icon_resources_verified'] = True
            report['installed_transparent_icon_assets_verified'] = True
            selftest = json.loads(execute(exe, 'selftest'))
            assert selftest['version'] == VERSION and selftest['native_aot'] is True
            assert selftest['checks'] == 15
            report['native_aot_selftest'] = selftest
            report['native_aot_fifteen_selftests_verified'] = True
            example = install / 'examples/one-click'
            sample_config = example / 'configuration.json'
            assert sample_config.is_file(), 'Installed one-click example is missing'
            config_template = json.loads(sample_config.read_text(encoding='utf-8'))
            assert config_template['profile'] == 'iw-resource63'
            assert config_template['asset_type'] == 'xanim'
            folder = example / 'hashed-assets'
            indexes = example / 'existing-indexes'
            assert folder.is_dir() and indexes.is_dir()
            source_before = fingerprints(example)
            profile = PROFILES['iw-resource63']
            existing = 'existing_animation'
            wanted = ['rex_mp_strafe_walk_1', 'rex_vm_misc_laser_pointer_fire']
            expected = {profile.digest(name): name for name in wanted}

            def execute_pipeline(config_path):
                # Match the actual GUI Job: every control callback must read
                # a real UTF-8 file, including during the duty-cycle waits.
                control_path = config_path.with_suffix('.control.txt')
                control_path.write_text('run', encoding='utf-8')
                stdout = execute(exe, 'run', config_path, '--control', control_path)
                assert control_path.read_bytes() == b'run'
                report['commands'][-1]['control_file_io'] = True
                report['control_file_runs'] = report.get('control_file_runs', 0) + 1
                return stdout

            def one_click(label, backend, keyword='', index_directory=indexes):
                config = dict(config_template, folder=str(folder), indexes=str(index_directory),
                              output=str(base / (label + ' Output')), backend=backend,
                              keyword=keyword, budget=100000, seconds=120)
                config_path = base / (label + ' configuration.json')
                config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
                stdout = execute_pipeline(config_path)
                events = []
                for line in stdout.splitlines():
                    if line.strip():
                        events.append(json.loads(line))
                assert events and events[-1].get('event') == 'result', stdout
                assert sum(e.get('event') == 'result' for e in events) == 1
                assert any(e.get('event') == 'progress' for e in events)
                result = events[-1]['result']
                assert result['status'] == 'completed' and result['full_keys']
                assert Path(result['run_dir']).resolve().is_relative_to(base.resolve())
                work = Path(result['run_dir']) / 'work.sqlite'
                assert work.is_file()
                work_files.append(work)
                persisted = json.loads((work.parent / 'report.json').read_text(encoding='utf-8'))
                assert persisted == result
                if backend == 'gpu':
                    assert any('OpenCL' in e.get('message', '') for e in events if e.get('event') == 'progress')
                    assert not any('GPU 故障' in e.get('message', '') for e in events)
                report['runs'].append({'label': label, 'backend': backend, 'keyword': keyword,
                                       'entries': result['entries'],
                                       'verified_target_matches': result['verified_target_matches'],
                                       'excluded_existing': result['excluded_existing'],
                                       'processed': result['processed']})
                assert fingerprints(example) == source_before, 'Bundled source example was modified'
                return result

            def check_export(result, values, keyword=''):
                output = Path(result['path'])
                assert decode_cdb((output / 'verified.cdb').read_bytes()) == values
                assert decode_cdb((output / 'hash_pkg/fnv1a_xanims_v2.cdb').read_bytes()) == values
                csv_path = Path(result['new_names_csv'])
                assert csv_path.is_absolute() and csv_path.is_file()
                assert csv_path.resolve() == (output / 'new_names.csv').resolve()
                assert csv_path.read_bytes() == (output / 'verified.csv').read_bytes()
                with csv_path.open(encoding='utf-8', newline='') as stream:
                    rows = list(csv.reader(stream))
                assert len(rows) == result['entries'] == len(values)
                assert all(len(row) == 2 for row in rows)
                assert {int(h, 16): name for h, name in rows} == values
                manifest = json.loads((output / 'manifest.json').read_text(encoding='utf-8'))
                assert manifest['full_keys'] and manifest['roundtrip_verified']
                assert manifest['target_profile'] == profile.id and manifest['keyword'] == keyword
                assert result['saluki_ready'], 'Automatic Saluki merge package was not generated'
                ready = Path(result['saluki_ready'])
                assert ready.resolve().is_relative_to(Path(result['run_dir']).resolve())
                assert (ready / 'merge-report.json').is_file()
                return ready

            # Use only installed example paths, with no original research input.
            for backend in ('cpu', 'gpu'):
                result = one_click('Example ' + backend.upper(), backend)
                assert result['verified_target_matches'] == 3 and result['entries'] == 2
                assert result['excluded_existing'] == 1
                assert result['saluki_exclusion_counts']['name_only'] == 1
                assert result['input']['hashed_files'] == 3
                ready = check_export(result, expected)
                assert decode_cdb((ready / 'hash_pkg/fnv1a_xanims_v2.cdb').read_bytes()) == expected
                assert existing not in expected.values()
            # Installed facade forwards estimate/method commands without a
            # developer runtime, including relative config paths.
            cpu_config_path=base/'Example CPU configuration.json'
            quote_events=[json.loads(line) for line in execute(exe,'run',cpu_config_path,'--estimate').splitlines() if line.strip()]
            quote=quote_events[-1]['estimate'];assert quote_events[-1]['event']=='estimate'
            assert quote['effective_bits']==63 and quote['target_count']==3
            assert quote['candidate_total']>=quote['budgeted_candidates']>=0
            assert quote['collision_expectation']==quote['budgeted_candidates']*3/(1<<63)
            repeated=one_click('Example CPU','cpu');assert repeated['processed']==0 and repeated['cached_hits']>=3
            check_export(repeated,expected)
            ledger_report=json.loads(execute(exe,'methods','report',base/'Example CPU Output'))
            assert ledger_report['summary'] and ledger_report['methods']
            report['estimate_and_cached_output_verified']=True
            report['methods_report_verified']=True
            audit_folder=base/'Local Audit';audit_folder.mkdir()
            audited_name='rex_validation_sound_alias';audited_key=PROFILES['fnv1a64'].digest(audited_name)
            (audit_folder/'fnv1a_soundbanks_aliases_v2.csv').write_text(f'{audited_key:016x},{audited_name}\n0000000000000001,invalid_candidate_only\n',encoding='utf-8')
            audit=json.loads(execute(exe,'table-audit',audit_folder,'--profile','fnv1a64'))
            assert audit['tables'][0]['profiles']['fnv1a64']['matches']==1
            imported_community=json.loads(execute(exe,'community','import',audit_folder,'--profile','fnv1a64'))
            assert imported_community['counts']['verified']==1 and imported_community['counts']['quarantined']==1
            report['table_audit_and_community_isolation_verified']=True
            report.update({'bundled_example_cpu_gpu_verified': True,
                           'three_verified_one_excluded_two_new': True,
                           'saluki_name_only_dedup_verified': True})

            # Keywords are applied to verified matches and final output, rather
            # than requiring a user-authored template or keyword-limited corpus.
            keyword = 'laser_pointer'
            filtered = one_click('Keyword', 'cpu', keyword)
            filtered_expected = {profile.digest(wanted[1]): wanted[1]}
            assert filtered['entries'] == 1 and filtered['excluded_existing'] == 0
            ready = check_export(filtered, filtered_expected, keyword)
            assert decode_cdb((ready / 'hash_pkg/fnv1a_xanims_v2.cdb').read_bytes()) == filtered_expected
            report['keyword_output_filter_verified'] = True

            # Exercise a real nonempty merge while leaving the installed index
            # untouched. The original same-package entry must survive exactly.
            copied_indexes = base / 'Copied Indexes'
            shutil.copytree(indexes, copied_indexes)
            preserved_name = 'existing_v2_unrelated_animation'
            preserved = {profile.digest(preserved_name): preserved_name}
            (copied_indexes / 'fnv1a_xanims_v2.cdb').write_bytes(encode_cdb(preserved))
            copied_before = fingerprints(copied_indexes)
            merged_result = one_click('Preserving Merge', 'cpu', index_directory=copied_indexes)
            assert merged_result['verified_target_matches'] == 3 and merged_result['entries'] == 2
            assert merged_result['excluded_existing'] == 1
            ready = check_export(merged_result, expected)
            assert decode_cdb((ready / 'hash_pkg/fnv1a_xanims_v2.cdb').read_bytes()) == {**preserved, **expected}
            merge = json.loads((ready / 'merge-report.json').read_text(encoding='utf-8'))
            assert merge['conflicts'] == []
            item = next(f for f in merge['files'] if f['file'] == 'fnv1a_xanims_v2.cdb')
            assert (item['old_entries'], item['incoming_entries'], item['merged_entries']) == (1, 2, 3)
            assert fingerprints(copied_indexes) == copied_before
            report['saluki_ready_merge_verified'] = True

            # Infer target names from other asset types, using both an existing
            # model index and a second directory of named exported assets. The
            # unknown identifiers occur in neither target-type template, so the
            # original title/number/view rules cannot produce these names.
            cross_fixture = base / 'Cross Asset Inference'
            cross_assets = cross_fixture / 'Hashed Assets'; cross_assets.mkdir(parents=True)
            cross_indexes = cross_fixture / 'Indexes'; cross_indexes.mkdir()
            related_assets = cross_fixture / 'Related Named Assets'; related_assets.mkdir()
            animation_template = 'iw9_vm_ar_mike4_reload_empty'
            pistol_template = 'iw9_vm_pi_papa320_reload_empty'
            sound_template = r'core\weapons\ar_mike4\wfoly_plr_ar_mike4_reload_01.lnn.85.48000.all'
            index_model = 'wpn_iw9_ar_alpha57_view'
            related_model = 'wpn_iw9_pi_kilo5_view'
            inferred_animation = 'iw9_vm_ar_alpha57_reload_empty'
            inferred_sound = r'core\weapons\ar_alpha57\wfoly_plr_ar_alpha57_reload_01.lnn.85.48000.all'
            related_animation = 'iw9_vm_pi_kilo5_reload_empty'
            cross_wanted = [inferred_animation, inferred_sound, related_animation]
            cross_expected = {profile.digest(name): profile.normalize(name) for name in cross_wanted}
            cross_target_kinds = {profile.digest(inferred_animation): 'xanim',
                profile.digest(inferred_sound): 'sndasset', profile.digest(related_animation): 'xanim'}
            template_values = {
                'fnv1a_xanims_v2.cdb': {profile.digest(animation_template): animation_template,
                                      profile.digest(pistol_template): pistol_template},
                'fnv1a_xsounds_v2.cdb': {profile.digest(sound_template): sound_template},
                'fnv1a_xmodels_v2.cdb': {profile.digest(index_model): index_model},
            }
            for package, values in template_values.items():
                (cross_indexes / package).write_bytes(encode_cdb(values))
            (related_assets / (related_model + '.bin')).write_bytes(b'named asset filename only')
            # The known animation is a real hash target too, exercising the
            # unchanged Saluki exclusion path in the same mixed-type search.
            for key, name in {**cross_expected, profile.digest(animation_template): animation_template}.items():
                prefix = 'sound' if key == profile.digest(inferred_sound) else 'anim'
                (cross_assets / f'{prefix}_{key:016x}.bin').write_bytes(b'hash filename only')
            cross_source_before = {
                'assets': fingerprints(cross_assets), 'indexes': fingerprints(cross_indexes),
                'related': fingerprints(related_assets),
            }

            def cross_asset_run(label, enabled, expected_values, verified, excluded, keyword=''):
                config = dict(config_template, folder=str(cross_assets), indexes=str(cross_indexes),
                    related_folder=str(related_assets), cross_asset=enabled, asset_type='auto',
                    output=str(cross_fixture / (label + ' Output')), dictionary='', profile=profile.id,
                    backend='cpu', keyword=keyword, low60=False, budget=100000, seconds=120)
                config_path = cross_fixture / (label + ' configuration.json')
                config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
                stdout = execute_pipeline(config_path)
                events = [json.loads(line) for line in stdout.splitlines() if line.strip()]
                assert events and events[-1].get('event') == 'result', stdout
                assert sum(event.get('event') == 'result' for event in events) == 1
                result = events[-1]['result']
                assert result['status'] == 'completed' and result['full_keys']
                assert result['verified_target_matches'] == verified
                assert result['excluded_existing'] == excluded
                assert result['entries'] == len(expected_values)
                assert result['input']['hashed_files'] == result['input']['recognized_files'] == 4
                assert result['input']['unique_assets'] == 4
                assert result['input']['detected_type_counts'] == {'xanim': 3, 'sndasset': 1}
                assert result['input']['models_excluded'] == result['input']['types_filtered'] == 0
                run_dir = Path(result['run_dir'])
                assert run_dir.resolve().is_relative_to(base.resolve())
                work = run_dir / 'work.sqlite'; assert work.is_file(); work_files.append(work)
                assert json.loads((run_dir / 'report.json').read_text(encoding='utf-8')) == result
                persisted_config = json.loads((run_dir / 'configuration.json').read_text(encoding='utf-8'))
                assert persisted_config['cross_asset'] is enabled
                assert Path(persisted_config['related_folder']).resolve() == related_assets.resolve()
                output = Path(result['path'])
                assert decode_cdb((output / 'verified.cdb').read_bytes()) == expected_values
                csv_path = Path(result['new_names_csv'])
                assert csv_path.is_absolute() and csv_path.resolve() == (output / 'new_names.csv').resolve()
                assert csv_path.read_bytes() == (output / 'verified.csv').read_bytes()
                with csv_path.open(encoding='utf-8', newline='') as stream:
                    rows = list(csv.reader(stream))
                assert all(len(row) == 2 for row in rows)
                assert {int(key, 16): name for key, name in rows} == expected_values
                # Python hashing is independent of the installed native CPU
                # candidate evaluator, and every output must be an input key.
                assert all(profile.digest(name) == key and key in cross_expected
                           for key, name in expected_values.items())
                assert all(key not in {profile.digest(animation_template), profile.digest(pistol_template),
                                      profile.digest(sound_template), profile.digest(index_model)}
                           for key in expected_values)
                expected_packages = {}
                for key, name in expected_values.items():
                    expected_packages.setdefault(SALUKI_PACKAGES[cross_target_kinds[key]], {})[key] = name
                assert set(path.name for path in (output / 'hash_pkg').glob('*.cdb')) == set(expected_packages)
                for package, values in expected_packages.items():
                    assert decode_cdb((output / 'hash_pkg' / package).read_bytes()) == values
                manifest = json.loads((output / 'manifest.json').read_text(encoding='utf-8'))
                assert manifest['full_keys'] and manifest['roundtrip_verified']
                assert manifest['target_profile'] == profile.id and manifest['keyword'] == keyword
                assert manifest['types'] == 'all-non-model' and manifest['entries'] == len(expected_values)
                if expected_values:
                    ready = Path(result['saluki_ready'])
                    assert ready.resolve().is_relative_to(run_dir.resolve())
                    merge = json.loads((ready / 'merge-report.json').read_text(encoding='utf-8'))
                    assert not merge['conflicts']
                    for package, values in expected_packages.items():
                        assert decode_cdb((ready / 'hash_pkg' / package).read_bytes()) == {
                            **template_values[package], **values}
                        merged = next(item for item in merge['files'] if item['file'] == package)
                        assert merged['old_entries'] == len(template_values[package])
                        assert merged['incoming_entries'] == len(values)
                        assert merged['merged_entries'] == len(template_values[package]) + len(values)
                else:
                    assert result['saluki_ready'] is None
                assert fingerprints(cross_assets) == cross_source_before['assets']
                assert fingerprints(cross_indexes) == cross_source_before['indexes']
                assert fingerprints(related_assets) == cross_source_before['related']
                report['runs'].append({'label': 'Cross Asset ' + label, 'backend': 'cpu',
                    'asset_type': 'auto', 'cross_asset': enabled, 'keyword': keyword,
                    'entries': result['entries'], 'verified_target_matches': result['verified_target_matches'],
                    'excluded_existing': result['excluded_existing'], 'processed': result['processed']})
                return result

            cross_enabled = cross_asset_run('Enabled', True, cross_expected, 4, 1)
            cross_disabled = cross_asset_run('Disabled', False, {}, 1, 1)
            cross_filtered_expected = {key: name for key, name in cross_expected.items() if 'alpha57' in name}
            cross_filtered = cross_asset_run('Keyword', True, cross_filtered_expected, 2, 0, 'alpha57')
            from validate_upstream_release import validate_upstream_features
            upstream_runs_before = report['control_file_runs']
            report['upstream_update_cases']=validate_upstream_features(base/'Upstream Update',execute_pipeline)
            report['upstream_control_file_runs'] = report['control_file_runs'] - upstream_runs_before
            assert report['upstream_control_file_runs'] == 2 * len(report['upstream_update_cases'])
            report['upstream_update_standalone_verified']=True
            report.update({'cross_asset_inference_verified': True,
                'cross_asset_index_model_clue_verified': True, 'cross_asset_related_folder_verified': True,
                'cross_asset_disabled_baseline_verified': True, 'cross_asset_keyword_filter_verified': True,
                'cross_asset_animation_sound_verified': True, 'cross_asset_source_files_unchanged': True,
                'cross_asset_fixture': {'index_model': index_model, 'related_model': related_model,
                    'animation_templates': [animation_template, pistol_template], 'sound_template': sound_template,
                    'inferred_names': list(cross_expected.values()), 'enabled_new_entries': cross_enabled['entries'],
                    'disabled_new_entries': cross_disabled['entries'],
                    'keyword_new_entries': cross_filtered['entries']}})

            # Every dropdown type uses the installed CPU pipeline end to end.
            # Fixtures contain filename keys only: no real media, research
            # directory, or source-tree CLI is needed to discover the names.
            expected_types = {'sndasset', 'image', 'xanim', 'material', 'soundbank',
                'soundbanktransient', 'animpkg', 'rawfile', 'scriptfile', 'scriptbundle',
                'stringtable', 'localize', 'weapon', 'attachment', 'structuredtable',
                'keyvaluepairs','soundbankalias','bone','scriptfield','dvar','omnvar'}
            assert set(ASSET_LABELS) == expected_types and len(ASSET_LABELS) == 21
            tested_types = []
            for kind in ASSET_LABELS:
                fixtures = base / 'Dropdown Types' / kind
                assets = fixtures / 'assets'; assets.mkdir(parents=True)
                type_indexes = fixtures / 'indexes'; type_indexes.mkdir()
                unrelated = 'existing_unrelated_' + kind
                (type_indexes / 'names.cdb').write_bytes(encode_cdb({1: unrelated}))
                target_name = 'validation_new_' + kind + '_asset'
                kind_game,kind_profile,kind_domain={
                    'soundbankalias':('COD2026','fnv1a64','soundbankalias'),
                    'bone':('MWII','fnv1a32','bone'),
                    'scriptfield':('BO6','bo6-script64','script'),
                    'dvar':('BO6','iw-dvar64','dvar'),
                    'omnvar':('BO6','bo6-omnvar64','omnvar'),
                }.get(kind,('COD2026',profile.id,''))
                target_hash = PROFILES[kind_profile].digest(target_name)
                dictionary = fixtures / 'candidate-names.txt'
                dictionary.write_text(target_name + '\n', encoding='utf-8')
                prefix = {'sndasset': 'sound', 'xanim': 'anim', 'soundbank': 'sndbank'}.get(kind, kind)
                suffixes = ('.json', '.csv') if kind == 'soundbank' else ('.bin',)
                for suffix in suffixes:
                    (assets / f'{prefix}_{target_hash:016x}{suffix}').write_bytes(b'filename-only fixture')
                assets_before = fingerprints(assets)
                indexes_before = fingerprints(type_indexes)
                dictionary_before = dictionary.read_bytes()
                config = dict(config_template, folder=str(assets), indexes=str(type_indexes),
                    output=str(fixtures / 'Output'), dictionary=str(dictionary), asset_type=kind,
                    profile=kind_profile,game=kind_game,hash_domain=kind_domain,backend='cpu', keyword='', exclude_material=kind != 'material',
                    low60=False, budget=100000, seconds=120)
                config_path = fixtures / 'configuration.json'
                config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
                stdout = execute_pipeline(config_path)
                events = [json.loads(line) for line in stdout.splitlines() if line.strip()]
                assert events and events[-1].get('event') == 'result', stdout
                assert sum(event.get('event') == 'result' for event in events) == 1
                result = events[-1]['result']
                assert result['status'] == 'completed' and result['full_keys']
                assert result['entries'] == result['verified_target_matches'] == 1
                assert result['excluded_existing'] == 0
                assert result['input']['detected_type_counts'] == {kind: len(suffixes)}
                assert result['input']['hashed_files'] == len(suffixes)
                assert result['input']['recognized_files'] == len(suffixes)
                assert result['input']['unique_assets'] == 1
                assert result['input']['types_filtered'] == result['input']['models_excluded'] == 0
                work = Path(result['run_dir']) / 'work.sqlite'
                assert work.is_file() and work.resolve().is_relative_to(base.resolve())
                work_files.append(work)
                assert json.loads((work.parent / 'report.json').read_text(encoding='utf-8')) == result
                values = {target_hash: target_name}
                output = Path(result['path'])
                assert decode_cdb((output / 'verified.cdb').read_bytes()) == values
                package = SALUKI_PACKAGES.get(kind, 'fnv1a_strings.cdb')
                if kind=='bone':package='fnv1a_bones.cdb'
                assert decode_cdb((output / 'hash_pkg' / package).read_bytes()) == values
                assert set(path.name for path in (output / 'hash_pkg').glob('*.cdb')) == {package}
                csv_path = Path(result['new_names_csv'])
                assert csv_path.is_absolute() and csv_path.resolve() == (output / 'new_names.csv').resolve()
                assert csv_path.read_bytes() == (output / 'verified.csv').read_bytes()
                with csv_path.open(encoding='utf-8', newline='') as stream:
                    assert list(csv.reader(stream)) == [[f'{target_hash:016x}', target_name]]
                manifest = json.loads((output / 'manifest.json').read_text(encoding='utf-8'))
                assert manifest['types'] == [kind] and manifest['roundtrip_verified'] and manifest['full_keys']
                assert manifest['target_profile'] == kind_profile and manifest['entries'] == 1
                assert manifest['exclude_material'] == (kind != 'material')
                ready = Path(result['saluki_ready'])
                assert ready.resolve().is_relative_to(work.parent.resolve())
                assert decode_cdb((ready / 'hash_pkg' / package).read_bytes()) == values
                assert fingerprints(assets) == assets_before and fingerprints(type_indexes) == indexes_before
                assert dictionary.read_bytes() == dictionary_before
                tested_types.append(kind)
                report['runs'].append({'label': 'Dropdown ' + kind, 'backend': 'cpu', 'asset_type': kind,
                    'entries': result['entries'], 'verified_target_matches': result['verified_target_matches'],
                    'excluded_existing': result['excluded_existing'], 'processed': result['processed'],
                    'detected_type_counts': result['input']['detected_type_counts'],
                    'filename_fixture_count': len(suffixes)})
            report['all_dropdown_types_pipeline_verified'] = len(tested_types) == 21
            report['tested_types'] = tested_types

            # Truncated keys remain explicitly unverified even when the native
            # evaluator finds their candidate name; no formal CSV/CDB/merge is
            # allowed to certify an inferred upper hash nibble.
            low_fixture = base / 'Low 60 Bit Safety'
            low_assets = low_fixture / 'assets'; low_assets.mkdir(parents=True)
            low_indexes = low_fixture / 'indexes'; low_indexes.mkdir()
            low_name = 'rex_mp_strafe_walk_1'
            full_key = profile.digest(low_name); assert full_key >= 1 << 60
            truncated_key = full_key & ((1 << 60) - 1)
            (low_assets / f'anim_{truncated_key:015x}.bin').write_bytes(b'low60 filename only')
            (low_indexes / 'names.cdb').write_bytes(encode_cdb({1: 'low60_unrelated_existing_name'}))
            low_dictionary = low_fixture / 'candidate.txt'
            low_dictionary.write_text(low_name + '\n', encoding='utf-8')
            low_before = {'assets': fingerprints(low_assets), 'indexes': fingerprints(low_indexes),
                          'dictionary': low_dictionary.read_bytes()}
            low_config = dict(config_template, folder=str(low_assets), indexes=str(low_indexes),
                output=str(low_fixture / 'Output'), dictionary=str(low_dictionary), profile=profile.id,
                asset_type='xanim', backend='cpu', cross_asset=False, related_folder='', keyword='',
                low60=True, budget=100000, seconds=120)
            low_config_path = low_fixture / 'configuration.json'
            low_config_path.write_text(json.dumps(low_config, ensure_ascii=False, indent=2), encoding='utf-8')
            low_stdout = execute_pipeline(low_config_path)
            low_events = [json.loads(line) for line in low_stdout.splitlines() if line.strip()]
            assert low_events and low_events[-1].get('event') == 'result', low_stdout
            assert sum(event.get('event') == 'result' for event in low_events) == 1
            low_result = low_events[-1]['result']
            assert low_result['status'] == 'completed' and low_result['full_keys'] is False
            assert low_result['entries'] == low_result['verified_target_matches'] == low_result['excluded_existing'] == 0
            assert low_result['pending_low60_candidates'] == 1 and low_result['saluki_ready'] is None
            low_run = Path(low_result['run_dir']); low_work = low_run / 'work.sqlite'
            assert low_work.is_file() and low_run.resolve().is_relative_to(base.resolve())
            work_files.append(low_work)
            assert json.loads((low_run / 'report.json').read_text(encoding='utf-8')) == low_result
            low_output = Path(low_result['path'])
            assert decode_cdb((low_output / 'verified.cdb').read_bytes()) == {}
            assert Path(low_result['new_names_csv']).read_bytes() == (low_output / 'verified.csv').read_bytes() == b''
            assert not list((low_output / 'hash_pkg').glob('*.cdb'))
            with (low_run / 'pending-low60.csv').open(encoding='utf-8', newline='') as stream:
                pending = list(csv.reader(stream))
            assert pending[0] == ['truncated_hash', 'candidate_name', 'status']
            assert len(pending) == 2 and int(pending[1][0], 16) == truncated_key
            assert pending[1][1:] == [low_name, 'UNVERIFIED_LOW60']
            with closing(sqlite3.connect(low_work)) as database:
                assert database.execute("SELECT COUNT(*) FROM evidence WHERE method='discovered'").fetchone()[0] == 0
                assert database.execute("SELECT COUNT(*) FROM evidence WHERE method='partial_match'").fetchone()[0] >= 1
            assert fingerprints(low_assets) == low_before['assets'] and fingerprints(low_indexes) == low_before['indexes']
            assert low_dictionary.read_bytes() == low_before['dictionary']
            report['runs'].append({'label': 'Low60 Safety', 'backend': 'cpu', 'entries': 0,
                'verified_target_matches': 0, 'excluded_existing': 0, 'processed': low_result['processed'],
                'pending_low60_candidates': 1})
            report['low60_never_certified_verified'] = True

            # Drive the installed NativeAOT facade while its Python worker is
            # active. Change the externally supplied control file after the
            # first search stage begins, then require a successful partial
            # report and an intact saved database rather than killing a process.
            pause_fixture = base / 'Stop And Save'
            pause_assets = pause_fixture / 'assets'; pause_assets.mkdir(parents=True)
            pause_indexes = pause_fixture / 'indexes'; pause_indexes.mkdir()
            absent_name = 'validation_pause_never_in_dictionary'
            (pause_assets / f'anim_{profile.digest(absent_name):016x}.bin').write_bytes(b'filename only')
            (pause_indexes / 'names.cdb').write_bytes(encode_cdb({1: 'validation_pause_existing_unrelated'}))
            pause_dictionary = pause_fixture / 'many-candidates.txt'
            pause_dictionary.write_text(''.join(f'validation_pause_candidate_{number:06d}\n'
                for number in range(131073)), encoding='utf-8')
            pause_before = {'assets': fingerprints(pause_assets), 'indexes': fingerprints(pause_indexes),
                            'dictionary': pause_dictionary.read_bytes()}
            pause_config = dict(config_template, folder=str(pause_assets), indexes=str(pause_indexes),
                output=str(pause_fixture / 'Output'), dictionary=str(pause_dictionary), profile=profile.id,
                asset_type='xanim', backend='cpu', cross_asset=False, related_folder='', keyword='',
                low60=False, budget=1000000, seconds=120)
            pause_config_path = pause_fixture / 'configuration.json'
            pause_config_path.write_text(json.dumps(pause_config, ensure_ascii=False, indent=2), encoding='utf-8')
            pause_control = pause_config_path.with_suffix('.control.txt'); pause_control.write_text('run', encoding='utf-8')
            pause_command = [str(exe), 'run', str(pause_config_path), '--control', str(pause_control)]
            pause_started = time.monotonic(); pause_events = []; pause_requested = False
            with subprocess.Popen(pause_command, cwd=base, env=env, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='strict') as process:
                deadline = threading.Timer(120, process.kill); deadline.daemon = True; deadline.start()
                try:
                    assert process.stdout is not None
                    for line in process.stdout:
                        if not line.strip(): continue
                        event = json.loads(line); pause_events.append(event)
                        if event.get('event') == 'progress' and event.get('message', '').startswith('阶段 '):
                            pause_control.write_text('pause', encoding='utf-8'); pause_requested = True
                            break
                    remaining_stdout, pause_stderr = process.communicate(timeout=120)
                    pause_exit_code = process.returncode
                finally:
                    deadline.cancel()
            pause_events.extend(json.loads(line) for line in remaining_stdout.splitlines() if line.strip())
            report['commands'].append({'args': pause_command, 'exit_code': pause_exit_code,
                'environment': 'system32-only', 'dotnet_runtime_root': 'nonexistent', 'control_file_io': True,
                'external_control_action': 'pause', 'seconds': round(time.monotonic() - pause_started, 3),
                'stderr_tail': pause_stderr[-4000:]})
            assert pause_exit_code == 0, str(pause_events) + pause_stderr
            assert pause_requested and pause_control.read_bytes() == b'pause'
            assert 'Traceback' not in pause_stderr and 'PYI' not in pause_stderr
            assert pause_events and pause_events[-1].get('event') == 'result'
            assert sum(event.get('event') == 'result' for event in pause_events) == 1
            pause_result = pause_events[-1]['result']
            assert pause_result['status'] == 'partial' and pause_result['full_keys']
            assert pause_result['entries'] == pause_result['verified_target_matches'] == pause_result['excluded_existing'] == 0
            assert pause_result['saluki_ready'] is None and pause_result['processed'] < 131074
            assert pause_result['stages'] and pause_result['stages'][-1]['status'] == 'paused'
            pause_run = Path(pause_result['run_dir']); pause_work = pause_run / 'work.sqlite'
            assert pause_work.is_file() and pause_run.resolve().is_relative_to(base.resolve())
            work_files.append(pause_work)
            assert json.loads((pause_run / 'report.json').read_text(encoding='utf-8')) == pause_result
            assert decode_cdb((Path(pause_result['path']) / 'verified.cdb').read_bytes()) == {}
            assert Path(pause_result['new_names_csv']).read_bytes() == b''
            with closing(sqlite3.connect(pause_work)) as database:
                assert database.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
                task_state = database.execute('SELECT status, position FROM tasks').fetchall()
                assert len(task_state) == 1 and task_state[0][0] == 'paused'
                assert task_state[0][1] == pause_result['processed']
            assert fingerprints(pause_assets) == pause_before['assets'] and fingerprints(pause_indexes) == pause_before['indexes']
            assert pause_dictionary.read_bytes() == pause_before['dictionary']
            report['control_file_runs'] += 1
            report['runs'].append({'label': 'Stop And Save', 'backend': 'cpu', 'entries': 0,
                'verified_target_matches': 0, 'excluded_existing': 0, 'processed': pause_result['processed'],
                'status': 'partial', 'task_status': 'paused'})
            report['external_control_pause_saved_verified'] = True
            report['native_aot_facade_control_forwarding_verified'] = True

            assert len(report['runs']) == len(ASSET_LABELS)+10
            assert report['control_file_runs'] == len(report['runs']) + report['upstream_control_file_runs']
            report['normal_runs_control_file_verified'] = True

            # Exercise the actual Avalonia start/progress/result chain as well
            # as its stop button path. gui-run is a validation entry into the
            # same MainWindow async method, not a substitute CLI calculator.
            def gui_run(config_path, expected_values, should_stop=False, reduced=False):
                args = ['gui-run', config_path, '--validation']
                if should_stop:
                    args.extend(['--stop-after', '1'])
                if reduced:
                    args.append('--reduced-effects')
                stdout = execute(exe, *args)
                events = [json.loads(line) for line in stdout.splitlines() if line.strip()]
                assert len(events) == 2 and events[0]['event'] == 'gui_validation', stdout
                state, event = events
                assert event['event'] == 'result'
                assert state['framework'] == 'Avalonia' and state['native_aot'] is True
                assert state['estimate_available'] is True and state['domain_dropdown'] is True
                assert state['style'] == 'liquid-glass'
                validate_glass_state(state, reduced=reduced)
                assert state['icon_present'] is True
                assert state['progress_events'] > 0
                assert state['start_button_enabled'] is True and state['stop_button_enabled'] is False
                assert state['result_button_enabled'] is True and state['csv_button_enabled'] is True
                assert state['stopped_by_request'] is should_stop and state['cross_asset_available'] is True
                assert state['related_folder_enabled'] is (not should_stop)
                assert isinstance(state['status'], str) and state['status']
                result = event['result']
                assert result['status'] == ('partial' if should_stop else 'completed')
                assert result['full_keys'] and result['entries'] == len(expected_values)
                run_dir = Path(result['run_dir']); work = run_dir / 'work.sqlite'
                assert run_dir.resolve().is_relative_to(base.resolve()) and work.is_file()
                work_files.append(work)
                assert json.loads((run_dir / 'report.json').read_text(encoding='utf-8')) == result
                output = Path(result['path'])
                assert decode_cdb((output / 'verified.cdb').read_bytes()) == expected_values
                csv_path = Path(result['new_names_csv'])
                assert csv_path.resolve() == (output / 'new_names.csv').resolve()
                assert csv_path.read_bytes() == (output / 'verified.csv').read_bytes()
                with csv_path.open(encoding='utf-8', newline='') as stream:
                    rows = list(csv.reader(stream))
                assert len(rows) == len(expected_values) and all(len(row) == 2 for row in rows)
                assert {int(key, 16): name for key, name in rows} == expected_values
                assert all(profile.digest(name) == key for key, name in expected_values.items())
                manifest = json.loads((output / 'manifest.json').read_text(encoding='utf-8'))
                assert manifest['full_keys'] and manifest['roundtrip_verified']
                assert manifest['target_profile'] == profile.id and manifest['entries'] == len(expected_values)
                assert result['pending_low60_candidates'] == 0
                assert not (run_dir / 'pending-low60.csv').exists()
                with closing(sqlite3.connect(work)) as database:
                    assert database.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
                report.setdefault('gui_runs', []).append({'config': str(config_path), 'state': state,
                    'reduced_effects': reduced,
                    'status': result['status'], 'entries': result['entries'], 'processed': result['processed'],
                    'verified_target_matches': result['verified_target_matches'],
                    'excluded_existing': result['excluded_existing']})
                return result

            gui_config = json.loads((cross_fixture / 'Enabled configuration.json').read_text(encoding='utf-8'))
            gui_config['output'] = str(cross_fixture / 'Avalonia GUI Output')
            gui_config_path = cross_fixture / 'gui-configuration.json'
            gui_config_path.write_text(json.dumps(gui_config, ensure_ascii=False, indent=2), encoding='utf-8')
            gui_quote_events=[json.loads(line) for line in execute(exe,'gui-estimate',gui_config_path,'--validation').splitlines() if line.strip()]
            assert len(gui_quote_events)==2 and gui_quote_events[0]['event']=='gui_validation'
            gui_quote_state=gui_quote_events[0];gui_quote=gui_quote_events[1]['estimate']
            assert gui_quote_events[1]['event']=='estimate' and gui_quote_state['estimate_available'] is True
            assert gui_quote_state['confirmation_required'] is True and gui_quote_state['start_button_enabled'] is True
            assert gui_quote_state['stop_button_enabled'] is False and gui_quote_state['result_button_enabled'] is False
            assert gui_quote['candidate_total']>0 and gui_quote['budgeted_candidates']>0
            assert not Path(gui_config['output']).exists()
            validate_glass_state(gui_quote_state)
            report['gui_estimate_before_confirmation_verified']=True
            report['gui_estimate_state']=gui_quote_state
            gui_completed = gui_run(gui_config_path, cross_expected)
            assert gui_completed['verified_target_matches'] == 4 and gui_completed['excluded_existing'] == 1
            assert gui_completed['cross_asset']['enabled'] is True
            gui_completed_ready = Path(gui_completed['saluki_ready'])
            for package in ('fnv1a_xanims_v2.cdb', 'fnv1a_xsounds_v2.cdb'):
                incoming = {key: name for key, name in cross_expected.items()
                    if SALUKI_PACKAGES[cross_target_kinds[key]] == package}
                assert decode_cdb((Path(gui_completed['path']) / 'hash_pkg' / package).read_bytes()) == incoming
                assert decode_cdb((gui_completed_ready / 'hash_pkg' / package).read_bytes()) == {
                    **template_values[package], **incoming}
            assert fingerprints(cross_assets) == cross_source_before['assets']
            assert fingerprints(cross_indexes) == cross_source_before['indexes']
            assert fingerprints(related_assets) == cross_source_before['related']
            report['avalonia_gui_start_progress_export_verified'] = True

            # A hit in the beginning of the literal plan must survive a UI
            # cancellation. A separate absent target keeps the remaining search
            # meaningful; the assertions use returned checkpoints, not a delay
            # or an assumed number of completed batches.
            gui_stop_fixture = base / 'Avalonia GUI Stop And Save'
            gui_stop_assets = gui_stop_fixture / 'assets'; gui_stop_assets.mkdir(parents=True)
            gui_stop_indexes = gui_stop_fixture / 'indexes'; gui_stop_indexes.mkdir()
            gui_stop_hit = 'aaa_validation_gui_stop_hit'
            gui_stop_unknown = 'zzz_validation_gui_stop_unknown'
            for name in (gui_stop_hit, gui_stop_unknown):
                (gui_stop_assets / f'anim_{profile.digest(name):016x}.bin').write_bytes(b'filename only')
            gui_stop_preserved = {1: 'gui_stop_unrelated_existing'}
            (gui_stop_indexes / 'fnv1a_xanims_v2.cdb').write_bytes(encode_cdb(gui_stop_preserved))
            gui_stop_dictionary = gui_stop_fixture / 'many-candidates.txt'
            gui_stop_dictionary.write_text(gui_stop_hit + '\n' + ''.join(
                f'validation_gui_stop_candidate_{number:06d}\n' for number in range(524289)), encoding='utf-8')
            gui_stop_before = {'assets': fingerprints(gui_stop_assets), 'indexes': fingerprints(gui_stop_indexes),
                               'dictionary': gui_stop_dictionary.read_bytes()}
            gui_stop_config = dict(config_template, folder=str(gui_stop_assets), indexes=str(gui_stop_indexes),
                output=str(gui_stop_fixture / 'Output'), dictionary=str(gui_stop_dictionary), profile=profile.id,
                asset_type='xanim', backend='cpu', cross_asset=False, related_folder='', keyword='',
                low60=False, budget=1000000, seconds=120)
            gui_stop_config_path = gui_stop_fixture / 'configuration.json'
            gui_stop_config_path.write_text(json.dumps(gui_stop_config, ensure_ascii=False, indent=2), encoding='utf-8')
            gui_stop_expected = {profile.digest(gui_stop_hit): gui_stop_hit}
            gui_stopped = gui_run(gui_stop_config_path, gui_stop_expected, should_stop=True)
            assert gui_stopped['verified_target_matches'] == 1 and gui_stopped['excluded_existing'] == 0
            assert 0 < gui_stopped['processed'] < 524291
            assert gui_stopped['stages'] and gui_stopped['stages'][-1]['status'] == 'paused'
            gui_stop_ready = Path(gui_stopped['saluki_ready'])
            assert decode_cdb((Path(gui_stopped['path']) / 'hash_pkg/fnv1a_xanims_v2.cdb').read_bytes()) == gui_stop_expected
            assert decode_cdb((gui_stop_ready / 'hash_pkg/fnv1a_xanims_v2.cdb').read_bytes()) == {
                **gui_stop_preserved, **gui_stop_expected}
            with closing(sqlite3.connect(Path(gui_stopped['run_dir']) / 'work.sqlite')) as database:
                checkpoints = database.execute('SELECT status, position FROM tasks').fetchall()
                assert len(checkpoints) == 1 and checkpoints[0] == ('paused', gui_stopped['processed'])
                found = database.execute("SELECT hash, name FROM evidence WHERE method='discovered'").fetchall()
                assert {int(key, 16): name for key, name in found} == gui_stop_expected
            assert fingerprints(gui_stop_assets) == gui_stop_before['assets']
            assert fingerprints(gui_stop_indexes) == gui_stop_before['indexes']
            assert gui_stop_dictionary.read_bytes() == gui_stop_before['dictionary']
            assert len(report['gui_runs']) == 2
            report['avalonia_gui_stop_saved_verified'] = True
            report['avalonia_gui_button_states_verified'] = True
            report['gui_stop_preserved_verified_hit'] = True

            # The explicit reduced-effects UI must retain the complete Python
            # name-search, independent verification and export path.
            gui_reduced_config = dict(gui_config, output=str(cross_fixture / 'Reduced Effects GUI Output'))
            gui_reduced_path = cross_fixture / 'gui-reduced-configuration.json'
            gui_reduced_path.write_text(json.dumps(gui_reduced_config, ensure_ascii=False, indent=2), encoding='utf-8')
            gui_reduced = gui_run(gui_reduced_path, cross_expected, reduced=True)
            assert gui_reduced['verified_target_matches'] == 4 and gui_reduced['excluded_existing'] == 1
            assert fingerprints(cross_assets) == cross_source_before['assets']
            assert fingerprints(cross_indexes) == cross_source_before['indexes']
            assert fingerprints(related_assets) == cross_source_before['related']
            assert len(report['gui_runs']) == 3
            report['reduced_effects_gui_export_verified'] = True

            # A genuine invalid input must produce a localized JSON error from
            # the installed EXE, with no traceback or PyInstaller failure banner.
            empty_assets = base / '空文件夹错误验收'; empty_assets.mkdir()
            error_config = dict(config_template, folder=str(empty_assets), indexes=str(indexes),
                output=str(base / 'Error Output'), backend='cpu', budget=100000, seconds=120)
            error_config_path = base / 'empty-folder-configuration.json'
            error_config_path.write_text(json.dumps(error_config, ensure_ascii=False, indent=2), encoding='utf-8')
            error_event = expect_error(exe, 'run', error_config_path)
            assert error_event['type'] == 'ValueError' and error_event['command'] == 'run'
            assert Path(error_event['input_folder']).resolve() == empty_assets.resolve()
            assert Path(error_event['config_file']).resolve() == error_config_path.resolve()
            assert '没有文件' in error_event['message']
            report['utf8_error_protocol_verified'] = True
            report['input_error_event'] = error_event

            # Capture the installed application's own widgets; this command
            # does not automate an external desktop application's interface.
            for tutorial in (False, True):
                screenshot = validation / (f'installed-{VERSION}-' + ('tutorial.png' if tutorial else 'gui.png'))
                args = ('screenshot', screenshot, '--tutorial', '--validation') if tutorial else ('screenshot', screenshot, '--validation')
                # Each is a required fresh-process check, not a retry: execute
                # immediately fails on any nonzero exit, even after valid JSON.
                for repetition in range(3):
                    if screenshot.exists():
                        screenshot.unlink()
                    state = json.loads(execute(exe, *args))
                    report['commands'][-1]['gui_exit_repetition'] = repetition + 1
                    assert state['single_page'] and state['algorithm_dropdown'] and state['asset_type_dropdown']
                    assert state['new_csv_button']
                    assert state['framework'] == 'Avalonia' and state['native_aot'] is True
                    assert state['style'] == 'liquid-glass'
                    validate_glass_state(state, tutorial=tutorial)
                    assert state['icon_present'] is True
                    assert state['cross_asset_checkbox'] and state['related_folder_picker']
                    assert state['cross_asset_default_enabled'] and state['worker_available']
                    assert state['tutorial_open'] == tutorial
                    if tutorial:
                        assert state['tutorial_loaded']
                    assert screenshot.is_file() and screenshot.stat().st_size > 10000
                    assert screenshot.read_bytes()[:8] == b'\x89PNG\r\n\x1a\n'
                    report.setdefault('screenshot_states', []).append(state)
                report['tutorial_screenshot' if tutorial else 'gui_screenshot'] = str(screenshot)
            report['gui_exit_repetitions_per_surface'] = 3

            minimum_screenshot = validation / f'installed-{VERSION}-gui-minimum.png'
            if minimum_screenshot.exists():
                minimum_screenshot.unlink()
            minimum_state = json.loads(execute(exe, 'screenshot', minimum_screenshot, '--validation', '--minimum'))
            assert minimum_state['framework'] == 'Avalonia' and minimum_state['native_aot'] is True
            assert minimum_state['style'] == 'liquid-glass'
            validate_glass_state(minimum_state)
            assert minimum_state['icon_present'] is True
            # Extended client chrome includes a small native resize-frame inset.
            assert 880 <= minimum_state['width'] <= 896 and 740 <= minimum_state['height'] <= 760
            assert minimum_state['single_page'] and minimum_state['algorithm_dropdown'] and minimum_state['asset_type_dropdown']
            assert minimum_state['new_csv_button'] and minimum_state['cross_asset_checkbox'] and minimum_state['related_folder_picker']
            assert minimum_state['cross_asset_default_enabled'] and minimum_state['worker_available']
            # A minimum-size layout may fit all inputs without overflowing;
            # this field reports whether scrolling is needed, not supported.
            assert isinstance(minimum_state['inputs_scrollable'], bool)
            assert minimum_state['tutorial_open'] is False
            assert minimum_screenshot.is_file() and minimum_screenshot.stat().st_size > 10000
            assert minimum_screenshot.read_bytes()[:8] == b'\x89PNG\r\n\x1a\n'
            report['minimum_window_state'] = minimum_state
            report['minimum_window_screenshot'] = str(minimum_screenshot)
            report['minimum_window_layout_verified'] = True

            for minimum in (False, True):
                reduced_screenshot = validation / f'installed-{VERSION}-gui-reduced{("-minimum" if minimum else "")}.png'
                if reduced_screenshot.exists():
                    reduced_screenshot.unlink()
                reduced_args = ['screenshot', reduced_screenshot, '--validation', '--reduced-effects']
                if minimum:
                    reduced_args.append('--minimum')
                reduced_state = json.loads(execute(exe, *reduced_args))
                validate_glass_state(reduced_state, reduced=True)
                assert reduced_state['framework'] == 'Avalonia' and reduced_state['native_aot'] is True
                assert reduced_state['icon_present'] is True
                assert reduced_state['single_page'] and reduced_state['algorithm_dropdown'] and reduced_state['asset_type_dropdown']
                assert reduced_state['new_csv_button'] and reduced_state['cross_asset_checkbox'] and reduced_state['related_folder_picker']
                assert reduced_state['cross_asset_default_enabled'] and reduced_state['worker_available']
                assert not reduced_state['tutorial_open']
                if minimum:
                    assert 880 <= reduced_state['width'] <= 896 and 740 <= reduced_state['height'] <= 760
                assert reduced_screenshot.is_file() and reduced_screenshot.stat().st_size > 10000
                assert reduced_screenshot.read_bytes()[:8] == b'\x89PNG\r\n\x1a\n'
                report.setdefault('reduced_effects_screenshots', []).append({'path': str(reduced_screenshot), 'state': reduced_state})
            report['reduced_effects_normal_and_minimum_verified'] = True

            # Packaging removes conflicting private ICU binaries. Also confirm
            # that normal usage succeeds with the developer machine's original
            # environment, including its PATH, rather than relying on isolation.
            normal_environment = os.environ.copy()
            normal_screenshot = validation / 'installed-gui-normal-path.png'
            if normal_screenshot.exists():
                normal_screenshot.unlink()
            normal_state = json.loads(execute(exe, 'screenshot', normal_screenshot,
                                             '--validation',
                                             environment=normal_environment))
            assert normal_state['single_page'] and normal_state['algorithm_dropdown']
            assert normal_state['asset_type_dropdown'] and not normal_state['tutorial_open']
            assert normal_state['new_csv_button']
            assert normal_state['bat_dropdown'] and normal_state['cordycep_capture_controls']
            assert normal_state['framework'] == 'Avalonia' and normal_state['native_aot'] is True
            assert normal_state['style'] == 'liquid-glass'
            validate_glass_state(normal_state)
            assert normal_state['icon_present'] is True
            assert normal_state['cross_asset_checkbox'] and normal_state['related_folder_picker']
            assert normal_state['cross_asset_default_enabled'] and normal_state['worker_available']
            assert normal_screenshot.is_file() and normal_screenshot.stat().st_size > 10000
            assert normal_screenshot.read_bytes()[:8] == b'\x89PNG\r\n\x1a\n'
            assert normal_environment.get('PATH') == os.environ.get('PATH')
            report['normal_path_gui_verified'] = True
            report['normal_path_gui_screenshot'] = str(normal_screenshot)
            report['normal_path_gui_state'] = normal_state

            # Inspect every resulting CDB with the installed independent Rust
            # reader, including empty, classified and merged outputs. Its new
            # location is inside the bundled worker, separate from the AOT UI.
            native_cdb_files = set()
            for work in work_files:
                result = json.loads((work.parent / 'report.json').read_text(encoding='utf-8'))
                output = Path(result['path'])
                native_cdb_files.add(output / 'verified.cdb')
                native_cdb_files.update((output / 'hash_pkg').glob('*.cdb'))
                if result['saluki_ready']:
                    native_cdb_files.update((Path(result['saluki_ready']) / 'hash_pkg').glob('*.cdb'))
            for path in sorted(native_cdb_files):
                native_values = json.loads(execute(cdb_reader, path))
                assert {int(key, 16): name for key, name in native_values.items()} == decode_cdb(path.read_bytes())
            report['independent_rust_cdb_reader_verified'] = True
            report['independent_cdb_files'] = len(native_cdb_files)
            assert fingerprints(example) == source_before
            report.update({'installation_verified': True, 'single_page_verified': True,
                           'algorithm_dropdown_verified': True, 'asset_type_dropdown_verified': True,
                           'tutorial_open_verified': True, 'no_research_inputs': True,
                           'system_only_path': True, 'source_files_unchanged': True,
                           'new_names_csv_verified': True, 'new_csv_button_verified': True,
                           'avalonia_gui_verified': True, 'native_aot_runtime_verified': True,
                           'cross_asset_checkbox_verified': True, 'related_folder_picker_verified': True,
                           'gui_window_icons_verified': True,
                           'liquid_glass_style_verified': True,
                           'liquid_glass_actual_renderer_verified': True,
                           'no_system_dotnet_required': True, 'no_system_python_required': True})
            from validate_snapshot_release import validate as validate_snapshot
            report['portable_snapshot_validation']=validate_snapshot(exe,base,env)
        finally:
            uninstaller = install / 'unins000.exe'
            if uninstaller.is_file():
                execute(uninstaller, '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
                        f'/LOG={validation / ("uninstall-" + VERSION + ".log")}')
        assert not exe.exists(), 'Validation application was not uninstalled'
        assert work_files and all(path.is_file() for path in work_files)
        assert copied_indexes.is_dir() and fingerprints(copied_indexes) == copied_before
        report['uninstall_verified'] = True
        report['user_work_preserved'] = True
    (validation / 'installer-validation.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Installed NativeAOT/Avalonia + bundled Python / CPU/GPU / cross-asset inference / 21 asset/domain types / low60 / stop-save / UTF-8 errors / name exclusion / keyword / merge / tutorial / uninstall verified')


if __name__ == '__main__':
    main()

