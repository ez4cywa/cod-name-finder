"""Capture the application's own single-page window and offline tutorial."""
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
for filename,extra in [('gui-one-click.png',[]),('tutorial-one-click.png',['--tutorial'])]:
    subprocess.run([sys.executable,'-m','finder','screenshot',str(ROOT/'validation'/filename),*extra],cwd=ROOT,check=True)
