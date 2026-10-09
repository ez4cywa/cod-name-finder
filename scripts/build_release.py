"""Build Avalonia NativeAOT UI + bundled Python engine + Windows EXE installer."""
import hashlib
import ctypes
import importlib.metadata as metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile
from build_installer import build_installer

ROOT=Path(__file__).resolve().parents[1]
VERSION='2.4.0'

def run(*args,cwd=ROOT):subprocess.run(args,cwd=cwd,check=True)

def assert_distribution_idle(folder):
    """Fail before deleting anything if a Windows payload is still mapped."""
    if sys.platform!='win32':return
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p]
    kernel.CreateFileW.restype=ctypes.c_void_p
    kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    for path in folder.rglob('*'):
        if not path.is_file() or path.suffix.lower() not in ('.exe','.dll','.pyd'):continue
        # Read with no sharing. Loaded images cannot share this handle.
        handle=kernel.CreateFileW(str(path),0x80000000,0,None,3,0,None)
        if handle in (None,ctypes.c_void_p(-1).value):
            raise RuntimeError('发布文件正在运行或不可独占读取，请先结束相关进程再构建：'+str(path))
        kernel.CloseHandle(handle)

def main(skip_tests=False):
    run(sys.executable,'scripts/generate_hash_registry.py','--check')
    run('cargo','build','--locked','--release','--manifest-path','native/Cargo.toml')
    if not skip_tests:run(sys.executable,'-m','pytest','-q')
    folder=ROOT/'dist'/VERSION/'CODNameFinder'
    if folder.exists():
        if not folder.resolve().is_relative_to((ROOT/'dist').resolve()):raise RuntimeError('Invalid distribution path')
        assert_distribution_idle(folder)
        shutil.rmtree(folder)
    run('dotnet','publish','CODNameFinder.App/CODNameFinder.App.csproj','-r','win-x64','-c','Release',
        '-p:RestoreLockedMode=true','-o',str(folder),cwd=ROOT/'dotnet')
    for path in folder.glob('*.pdb'):path.unlink()
    run(sys.executable,'-m','PyInstaller','--noconfirm','--onedir','--console','--name','NameFinder.Engine',
        '--distpath',str(ROOT/'dist'/(VERSION+'-worker')),'--workpath',str(ROOT/'build'/('engine-'+VERSION)),
        '--specpath',str(ROOT/'build'),
        '--collect-all','pyopencl','--collect-all','pytools','--collect-all','lz4',
        '--exclude-module','PySide6','--exclude-module','shiboken6','--exclude-module','finder.gui',
        '--exclude-module','matplotlib','--exclude-module','scipy','--exclude-module','IPython',
        '--exclude-module','pytest',
        '--icon',str(ROOT/'assets/cod-name-finder.ico'),
        '--add-binary',str(ROOT/'native/target/release/finder_native.dll')+';.',
        '--add-binary',str(ROOT/'native/target/release/cdb-inspect.exe')+';.',str(ROOT/'engine_launch.py'))
    shutil.copytree(ROOT/'dist'/(VERSION+'-worker')/'NameFinder.Engine',folder/'engine')
    # Stable generator provenance must hash the same source bytes on a new PC.
    # PyInstaller's executable module archive alone does not expose those files.
    provenance=folder/'engine/_internal/finder';provenance.mkdir(parents=True,exist_ok=True)
    for name in ('autoplans.py','crossassets.py','weapon.py','store.py','candidates.py','completedcache.py',
                 'soundplans.py','soundbyte.py','spellings.py','typedplans.py','community.py',
                 'upstream.py','contribution_evidence.py','github_api.py','github_credentials.py',
                 'scanidentity.py','backends.py','peeling.py','registry.py','formats.py','generated_registry.py',
                 'hashing.py','pipeline.py','engine.py','asset_names.py','methods.py','snapshot.py','cordycep.py','batch_loader.py','cordycep_profiles.json'):
        shutil.copy2(ROOT/'finder'/name,provenance/name)
    assert not any('pyside' in p.name.lower() or 'qt6' in p.name.lower() for p in (folder/'engine').rglob('*'))
    for name in ('README.md','CONTRIBUTING.md','LICENSE','THIRD_PARTY_NOTICES.md'):shutil.copy2(ROOT/name,folder/name)
    (folder/'docs').mkdir()
    shutil.copy2(ROOT/'docs/user-guide.zh-CN.md',folder/'docs/user-guide.zh-CN.md')
    shutil.copytree(ROOT/'docs/images',folder/'docs/images')
    glass_research=ROOT/'docs/liquid-glass-research.zh-CN.md'
    if glass_research.is_file():shutil.copy2(glass_research,folder/'docs'/glass_research.name)
    for name in ('hash-registry.json','hash-algorithm-coverage.md','hash-slinging-slasher-adaptation.zh-CN.md','adaptation-implementation.zh-CN.md','capture-feasibility.zh-CN.md','cordycep-local-research.zh-CN.md','cordycep-latest-research.zh-CN.md','building.zh-CN.md','release-2.2.2.zh-CN.md','upstream-update-20261009.zh-CN.md','release-2.3.0.zh-CN.md','release-2.4.0.zh-CN.md','upstream-contribution.zh-CN.md'):
        source_document=ROOT/'docs'/name
        if source_document.is_file():shutil.copy2(source_document,folder/'docs'/name)
    shutil.copytree(ROOT/'examples/one-click',folder/'examples/one-click')
    shutil.copytree(ROOT/'assets',folder/'assets')
    architecture={'version':VERSION,'ui':'Avalonia 12.1.3','ui_style':'liquid-glass','ui_compilation':'dotnet-native-aot',
        'glass_library':'Fluid.Avalonia.Acrylic 1.4.0',
        'glass_library_source_commit':'013590eaa93666d368d775efdb3d7715591a4232',
        'glass_background':'application-internal-skia-sampling',
        'target':'win-x64','backend':'bundled-python','backend_executable':'engine/NameFinder.Engine.exe',
        'requires_system_python':False,'requires_system_dotnet':False,'protocol':'utf8-json-lines',
        'stop':'control-file-pause-and-export'}
    architecture.update(hash_profiles=20,asset_types=21,hash_registry='generated-single-source',
        capture='external-local-cordycep-read-only',capture_games=['COD2026 Beta','BO7'],
        capture_launch='user-selected-local-bat-windows-owned-job',compatible_loader_builds=2,
        snapshot='CODSNAP2-raw64-per-pool-domain',offline_snapshot=True,
        supported_capture_pools=16,cordycep_bundled=False,
        search='bounded-forward-or-reversible-peeling',sweep_ledger='content-addressed-intervals-and-complete-runs',
        community_sync='optional-read-only-default-off',
        upstream_reference='dbe25197cee05b8315b4effff1841ed4868152f0',
        modern_ids='capture-local-type-map-63-bit; full64-alias-output-refused',
        observed_search=['sound-linked-namespaces','alias-file-families','inverse-sound-final-byte',
                         'animation-to-alias','typed-weapon-image-material'],
        source_spellings='bounded-restoration-and-source-domain-rehash',
        scan_cache_identity='source-and-actual-native-dll-sha256',
        upstream_contribution='opt-in-verified-findings-github-rest-graphql-no-git',
        upstream_credentials='windows-credential-manager-optional',
        upstream_contribution_types=['xanim','image','material','sound_asset','sound_alias'],
        upstream_automatic='session-only-default-off-completed-full-key-only',
        interactive_control_content='horizontal-and-vertical-center')
    (folder/'architecture.json').write_text(json.dumps(architecture,indent=2),encoding='utf-8')
    licenses=folder/'licenses';licenses.mkdir()
    python_license=Path(sys.base_prefix)/'LICENSE.txt'
    if python_license.is_file():shutil.copy2(python_license,licenses/'Python-LICENSE.txt')
    inventory=[]
    for pkg in ('numpy','pyopencl','pytools','lz4','siphash24','platformdirs','typing_extensions','PyInstaller'):
        dist=metadata.distribution(pkg)
        inventory.append({'name':pkg,'version':dist.version,'license':dist.metadata.get('License'),
            'license_expression':dist.metadata.get('License-Expression')})
        for file in dist.files or []:
            if any(w in str(file).lower() for w in ('license','copyright','copying','notice')):
                original=Path(dist.locate_file(file))
                if original.is_file():
                    target=licenses/'python'/pkg/str(file);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(original,target)
    (licenses/'python-inventory.json').write_text(json.dumps(inventory,indent=2),encoding='utf-8')
    nuget=Path.home()/'.nuget/packages'
    lock=json.loads((ROOT/'dotnet/CODNameFinder.App/packages.lock.json').read_text(encoding='utf-8'))
    for packages in lock['dependencies'].values():
        for name,item in packages.items():
            if item.get('type')=='Project':continue
            location=nuget/name.lower()/item['resolved']
            for original in location.rglob('*'):
                if original.is_file() and (original.suffix=='.nuspec' or original.name.lower().startswith(('license','notice','copying'))):
                    target=licenses/'dotnet'/name/original.relative_to(location);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(original,target)
    shutil.copy2(ROOT/'dotnet/CODNameFinder.App/packages.lock.json',licenses/'dotnet-packages.lock.json')
    for family in ('microsoft.dotnet.ilcompiler','microsoft.netcore.app.runtime.win-x64'):
        for location in (nuget/family).glob('*'):
            for name in ('LICENSE.TXT','THIRD-PARTY-NOTICES.TXT'):
                original=location/name
                if original.is_file():
                    target=licenses/'dotnet-runtime'/family/location.name/name
                    target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(original,target)
    cargo=Path.home()/'.cargo/registry/src'
    for crate in ('lz4_flex','twox-hash','serde_json','serde_core','itoa','memchr','zmij'):
        for location in cargo.glob('*/'+crate+'-*'):
            for original in location.glob('*'):
                if original.is_file() and original.name.upper().startswith(('LICENSE','COPYING','NOTICE')):
                    target=licenses/'rust'/location.name/original.name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(original,target)
    releases=ROOT/'releases';releases.mkdir(exist_ok=True)
    installer=build_installer(folder,VERSION,releases)
    source=releases/f'CODNameFinder-{VERSION}-source.zip'
    with zipfile.ZipFile(source,'w',zipfile.ZIP_DEFLATED) as archive:
        for name in ('finder','native/src','scripts','tests','examples','docs','installer','dotnet','assets'):
            for path in (ROOT/name).rglob('*'):
                if path.is_file() and not any(part in ('__pycache__','bin','obj') for part in path.relative_to(ROOT).parts):
                    archive.write(path,path.relative_to(ROOT))
        for name in ('.gitignore','.gitattributes','CONTRIBUTING.md','README.md','LICENSE','THIRD_PARTY_NOTICES.md','pyproject.toml','requirements.lock.txt','requirements-verify.txt','launch.py','engine_launch.py','native/Cargo.toml','native/Cargo.lock'):
            archive.write(ROOT/name,name)
    checks={path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in (source,installer)}
    (releases/'SHA256SUMS.txt').write_text('\n'.join(f'{digest}  {name}' for name,digest in checks.items())+'\n',encoding='utf-8')
    (releases/'release.json').write_text(json.dumps({'version':VERSION,'publication':'local-only',
        'distribution':'exe-installer','architecture':architecture,'tutorial_bundled':True,'files':checks,
        'saluki_live_verified':False,'soak_8h_completed':False},indent=2),encoding='utf-8')
    print(json.dumps(checks,indent=2))

if __name__=='__main__':main(skip_tests='--skip-tests' in sys.argv)
