import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import sys

import pytest

from finder.batch_loader import OwnedBatchProcess, validate_script


def test_batch_script_must_resolve_inside_selected_root(tmp_path):
    root=tmp_path/'中文 空格';root.mkdir()
    script=root/'启动 测试.BAT';script.write_text('@echo off\r\n',encoding='ascii')
    assert validate_script(root,script.name)==script.resolve()
    outside=tmp_path/'outside.bat';outside.write_text('echo outside',encoding='ascii')
    with pytest.raises(ValueError,match='外部脚本'):
        validate_script(root,outside)
    wrong=root/'note.txt';wrong.write_text('echo nope',encoding='ascii')
    with pytest.raises(ValueError,match='BAT'):
        validate_script(root,wrong)
    special=root/'percent%script.bat';special.write_text('echo nope',encoding='ascii')
    with pytest.raises(ValueError,match='%'):
        validate_script(root,special)


windows=pytest.mark.skipif(os.name!='nt' or ctypes.sizeof(ctypes.c_void_p)!=8,
                          reason='native Windows64 job integration')


@windows
def test_batch_runs_all_lines_at_chinese_space_path_and_returns_exit_code(tmp_path):
    root=tmp_path/'中文 根目录 空格';root.mkdir()
    script=root/'回显 测试.bat'
    script.write_text('@echo off\necho first-line\necho second-line\nexit /b 7\n',encoding='ascii')
    with OwnedBatchProcess(root,script) as child:
        data=child.stdout.read()
        assert child.wait(timeout=5)==7
        assert data.splitlines()==[b'first-line',b'second-line']
        assert child.returncode==7
        assert not child.owns(os.getpid())
    assert child.stdin.closed and child.stdout.closed
    assert child.poll()==7
    assert child.job_process_ids()==() and not child.has_live_processes()
    child.close()


@windows
def test_batch_pipes_allow_interactive_child_input(tmp_path):
    root=tmp_path/'中文 交互';root.mkdir()
    helper=root/'pipe_reader.py'
    helper.write_text("import sys\nprint('READY',flush=True)\nline=sys.stdin.buffer.readline()\n"
                      "sys.stdout.buffer.write(b'READ:'+line);sys.stdout.buffer.flush()\n",encoding='ascii')
    script=root/'交互.bat'
    script.write_text(f'@echo off\n"{sys.executable}" "{helper}"\n',encoding='utf-8')
    # CMD decodes BAT paths using its OEM codepage. Use ASCII relative helper
    # name to leave the Chinese directory to Unicode CreateProcess/cwd.
    script.write_text(f'@echo off\n"{sys.executable}" pipe_reader.py\n',encoding='ascii')
    with OwnedBatchProcess(root,script) as child:
        assert child.stdout.readline().strip()==b'READY'
        child.stdin.write(b'keyword\r\n');child.stdin.flush()
        assert child.stdout.read().splitlines()==[b'READ:keyword']
        assert child.wait(timeout=5)==0


@windows
def test_job_owns_nested_children_and_closes_only_its_process_tree(tmp_path):
    root=tmp_path/'中文 后代 空格';root.mkdir()
    helper=root/'descendants.py'
    helper.write_text("import os,subprocess,sys,time\n"
                      "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])\n"
                      "print(str(os.getpid())+','+str(child.pid),flush=True)\n"
                      "time.sleep(60)\n",encoding='ascii')
    script=root/'后代 测试.bat'
    script.write_text(f'@echo off\n"{sys.executable}" descendants.py\n',encoding='ascii')
    unrelated=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],
                               creationflags=subprocess.CREATE_NO_WINDOW)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
    kernel.WaitForSingleObject.restype=wintypes.DWORD
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    kernel.CloseHandle.restype=wintypes.BOOL
    handles=[];child=None
    try:
        child=OwnedBatchProcess(root,script)
        parent_pid,nested_pid=map(int,child.stdout.readline().strip().split(b','))
        assert child.owns(child.pid) and child.owns(parent_pid) and child.owns(nested_pid)
        assert {child.pid,parent_pid,nested_pid}.issubset(child.job_process_ids())
        assert child.has_live_processes()
        assert not child.owns(unrelated.pid) and not child.owns(os.getpid())
        with pytest.raises(subprocess.TimeoutExpired):
            child.wait(timeout=0)
        for pid in (parent_pid,nested_pid):
            handle=kernel.OpenProcess(0x00100000,False,pid)
            assert handle
            handles.append(handle)
        child.close()
        assert child.poll() is not None
        for handle in handles:
            assert kernel.WaitForSingleObject(handle,5000)==0
        assert unrelated.poll() is None
        assert not child.owns(parent_pid)
    finally:
        if child is not None:child.close()
        for handle in handles:kernel.CloseHandle(handle)
        unrelated.terminate();unrelated.wait(timeout=5)


@windows
def test_failed_job_assignment_never_executes_bat(tmp_path,monkeypatch):
    from finder import batch_loader
    root=tmp_path/'assignment-failure';root.mkdir()
    script=root/'failure.bat';script.write_text('@echo started>executed.txt\n',encoding='ascii')
    native=batch_loader._kernel()
    class RejectAssignment:
        def __getattr__(self,name):return getattr(native,name)
        def AssignProcessToJobObject(self,*_):
            ctypes.set_last_error(5)
            return False
    monkeypatch.setattr(batch_loader,'_kernel',lambda:RejectAssignment())
    with pytest.raises(ValueError,match='归属 Job'):
        OwnedBatchProcess(root,script)
    assert not (root/'executed.txt').exists()


@windows
def test_async_start_child_remains_owned_after_cmd_exits(tmp_path):
    root=tmp_path/'异步 子进程';root.mkdir()
    (root/'detached.py').write_text("import os,time\nprint(os.getpid(),flush=True)\ntime.sleep(60)\n",encoding='ascii')
    script=root/'start.bat'
    script.write_text(f'@echo off\nstart "" /B "{sys.executable}" detached.py\nexit /b 0\n',encoding='ascii')
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
    kernel.WaitForSingleObject.restype=wintypes.DWORD
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    kernel.CloseHandle.restype=wintypes.BOOL
    handle=None
    with OwnedBatchProcess(root,script) as child:
        pid=int(child.stdout.readline().strip())
        assert child.wait(timeout=5)==0
        assert child.owns(pid)
        assert pid in child.job_process_ids() and child.has_live_processes()
        handle=kernel.OpenProcess(0x00100000,False,pid)
        assert handle
        try:
            child.close()
            assert kernel.WaitForSingleObject(handle,5000)==0
            assert child.job_process_ids()==() and not child.has_live_processes()
        finally:
            kernel.CloseHandle(handle)
