"""Search process isolation: atomic controls, persistent checkpoints, bounded logs."""
import json
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
from .store import Store

def command():
    if getattr(sys,'frozen',False):return [sys.executable]
    return [sys.executable,'-m','finder']

def isolated(work,task,progress,control):
    with tempfile.TemporaryDirectory(prefix='finder-control-') as folder:
        control_path=Path(folder)/'control.txt'
        control_path.write_text('run',encoding='utf-8')
        flags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0
        proc=subprocess.Popen(command()+['--work',str(work),'worker',task,str(control_path)],
            stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',
            creationflags=flags)
        lines=queue.Queue()
        def reader():
            for line in proc.stdout:lines.put(line)
            lines.put(None)
        thread=threading.Thread(target=reader,daemon=True);thread.start()
        action='run';tail=[]
        try:
            while True:
                desired=control()
                if desired!=action:
                    temp=control_path.with_suffix('.tmp');temp.write_text(desired,encoding='utf-8');temp.replace(control_path)
                    action=desired
                try:line=lines.get(timeout=0.1)
                except queue.Empty:continue
                if line is None:break
                tail.append(line.strip());tail=tail[-20:]
                try:
                    item=json.loads(line)
                    if isinstance(item,dict) and 'position' in item and 'message' in item:
                        progress(item['position'],item['message'])
                except ValueError:progress(0,line.strip())
            proc.wait()
            if proc.returncode:
                raise RuntimeError('查找进程异常退出，已提交断点保留：\n'+'\n'.join(tail))
            s=Store(work)
            try:return s.task(task)
            finally:s.close()
        finally:
            if proc.poll() is None:
                control_path.write_text('pause',encoding='utf-8')
                try:proc.wait(timeout=10)
                except subprocess.TimeoutExpired:proc.terminate();proc.wait()
            proc.stdout.close()

