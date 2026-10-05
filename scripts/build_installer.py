"""Build the mandatory EXE distribution with a verified local Inno compiler."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]

def build_installer(folder, version, output):
    candidates=[os.environ.get('INNO_ISCC'),shutil.which('ISCC'),
        str(ROOT/'tooling/inno-6.7.3/ISCC.exe'),
        r'C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
        r'C:\Program Files (x86)\Inno Setup 7\ISCC.exe']
    compiler=next((Path(p) for p in candidates if p and Path(p).is_file()),None)
    if compiler is None:
        raise RuntimeError('Install Inno Setup or set INNO_ISCC to ISCC.exe; EXE installer is required for release')
    subprocess.run([str(compiler),f'/DAppVersion={version}',f'/DSourceRoot={Path(folder).resolve()}',
        f'/DOutputRoot={Path(output).resolve()}',str(ROOT/'installer/setup.iss')],check=True,cwd=ROOT)
    installer=Path(output)/f'CODNameFinder-{version}-Setup.exe'
    if not installer.is_file():raise RuntimeError('Installer compiler did not produce an EXE')
    return installer

if __name__=='__main__':
    sys.path.insert(0,str(ROOT))
    from finder import VERSION
    print(build_installer(ROOT/'dist'/VERSION/'CODNameFinder',VERSION,ROOT/'releases'))
