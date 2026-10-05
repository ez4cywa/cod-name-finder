"""Run a selected local BAT in a job owned by this request.

The suspended CMD process joins the job before it can create a child. Closing
the non-inherited job handle terminates its process tree, without finding or
terminating unrelated processes by name. No game process memory is written.

Win32 contracts:
https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects
https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_process_id_list
"""
import ctypes
from ctypes import wintypes
import math
import os
from pathlib import Path
import struct
import subprocess
import time

if os.name == 'nt':
    import _winapi
    import msvcrt


_KILL_ON_JOB_CLOSE = 0x00002000
_CREATE_SUSPENDED = 0x00000004
_EXTENDED_LIMIT_INFORMATION = 9
_BASIC_PROCESS_ID_LIST = 3
_ERROR_MORE_DATA = 234
_MAX_JOB_PROCESSES = 65536


def validate_script(directory, script):
    """Resolve a regular BAT directly inside the selected loader directory."""
    try:
        root = Path(directory).resolve(strict=True)
        selected = Path(script)
        path = (selected if selected.is_absolute() else root / selected).resolve(strict=True)
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        raise ValueError('所选 Cordycep 启动脚本不存在或路径无效') from error
    if not root.is_dir() or not path.is_file() or path.suffix.lower() != '.bat':
        raise ValueError('请选择 Cordycep 目录根目录内的 BAT 启动脚本')
    if path.parent != root:
        raise ValueError('启动脚本必须位于所选 Cordycep 目录根目录，不能使用外部脚本')
    if any(character in str(path) for character in '%!\r\n\x00"'):
        raise ValueError('启动脚本路径不能包含 %、!、引号或换行，请使用普通中文或空格路径')
    return path


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ('process_user_time', ctypes.c_longlong),
        ('job_user_time', ctypes.c_longlong),
        ('flags', wintypes.DWORD),
        ('minimum_working_set', ctypes.c_size_t),
        ('maximum_working_set', ctypes.c_size_t),
        ('active_process_limit', wintypes.DWORD),
        ('affinity', ctypes.c_size_t),
        ('priority_class', wintypes.DWORD),
        ('scheduling_class', wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in (
        'read_operations', 'write_operations', 'other_operations',
        'read_transfers', 'write_transfers', 'other_transfers')]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ('basic', _BasicLimits), ('io', _IoCounters),
        ('process_memory_limit', ctypes.c_size_t),
        ('job_memory_limit', ctypes.c_size_t),
        ('peak_process_memory', ctypes.c_size_t),
        ('peak_job_memory', ctypes.c_size_t),
    ]


def _kernel():
    if os.name != 'nt' or ctypes.sizeof(ctypes.c_void_p) != 8:
        raise ValueError('BAT 启动捕获需要 64 位 Windows')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    signatures = {
        'CreateJobObjectW': ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
        'SetInformationJobObject': ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
        'AssignProcessToJobObject': ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
        'QueryInformationJobObject': ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                      ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
        'ResumeThread': ([wintypes.HANDLE], wintypes.DWORD),
        'GetSystemDirectoryW': ([wintypes.LPWSTR, wintypes.UINT], wintypes.UINT),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(kernel, name)
        function.argtypes = arguments
        function.restype = result
    return kernel


def _failure(message):
    return ValueError(f'{message}（Windows 错误 {ctypes.get_last_error()}）；未使用无归属保护的启动方式')


def _system_cmd(kernel):
    text = ctypes.create_unicode_buffer(32768)
    length = kernel.GetSystemDirectoryW(text, len(text))
    if not 0 < length < len(text):
        raise _failure('无法定位 Windows 系统 CMD')
    path = (Path(text.value) / 'cmd.exe').resolve(strict=True)
    if not path.is_absolute() or not path.is_file():
        raise ValueError('Windows 系统 CMD 不存在')
    return path


class OwnedBatchProcess:
    """Small binary-pipe Popen interface, with a suspended-start job boundary.

    ``pid`` and ``returncode`` belong to the CMD root. ``owns(pid)`` also checks
    living descendants, including a loader started by BAT ``start`` commands.
    A naturally exited CMD can leave owned descendants; ``close`` still closes
    the job. The caller must use actual loader state to identify the loader PID.
    """
    def __init__(self, directory, script):
        self.stdin = None
        self.stdout = None
        self.pid = None
        self.returncode = None
        self._process = None
        self._job = None
        self._assigned = False
        self._closed = False
        self.script = validate_script(directory, script)
        self.directory = self.script.parent
        self.kernel = _kernel()
        self.command = _system_cmd(self.kernel)
        self.args = f'"{self.command}" /D /Q /V:OFF /S /C ""{self.script}""'
        thread = None
        descriptors = set()
        try:
            self._job = self.kernel.CreateJobObjectW(None, None)
            if not self._job:
                raise _failure('无法建立 BAT 进程归属 Job')
            limits = _ExtendedLimits()
            limits.basic.flags = _KILL_ON_JOB_CLOSE
            if not self.kernel.SetInformationJobObject(self._job, _EXTENDED_LIMIT_INFORMATION,
                                                       ctypes.byref(limits), ctypes.sizeof(limits)):
                raise _failure('无法启用本次 BAT 进程树退出保护')

            stdin_read, stdin_write = os.pipe()
            descriptors.update((stdin_read, stdin_write))
            stdout_read, stdout_write = os.pipe()
            descriptors.update((stdout_read, stdout_write))
            # Only these two handles enter the child. The job, process and
            # parent-side pipe handles are never inherited.
            os.set_inheritable(stdin_read, True)
            os.set_inheritable(stdout_write, True)
            os.set_inheritable(stdin_write, False)
            os.set_inheritable(stdout_read, False)
            input_handle = msvcrt.get_osfhandle(stdin_read)
            output_handle = msvcrt.get_osfhandle(stdout_write)
            startup = subprocess.STARTUPINFO()
            startup.dwFlags = _winapi.STARTF_USESTDHANDLES | _winapi.STARTF_USESHOWWINDOW
            startup.wShowWindow = _winapi.SW_HIDE
            startup.hStdInput = input_handle
            startup.hStdOutput = output_handle
            startup.hStdError = output_handle
            startup.lpAttributeList = {'handle_list': [input_handle, output_handle]}
            environment = dict(os.environ)
            environment['ComSpec'] = str(self.command)
            process, thread, self.pid, _ = _winapi.CreateProcess(
                str(self.command), self.args, None, None, True,
                _CREATE_SUSPENDED | subprocess.CREATE_NO_WINDOW,
                environment, str(self.directory), startup)
            self._process = process
            # CMD is still suspended: failure here can never execute the BAT.
            if not self.kernel.AssignProcessToJobObject(self._job, self._process):
                raise _failure('无法将 BAT 加入本次进程归属 Job')
            self._assigned = True
            self.stdin = os.fdopen(stdin_write, 'wb', buffering=0)
            descriptors.remove(stdin_write)
            self.stdout = os.fdopen(stdout_read, 'rb', buffering=0)
            descriptors.remove(stdout_read)
            # Remove parent's extra child-side pipe handles before execution.
            for descriptor in (stdin_read, stdout_write):
                os.close(descriptor)
                descriptors.remove(descriptor)
            if self.kernel.ResumeThread(thread) != 1:
                raise _failure('无法恢复已归属的 BAT 主线程')
        except BaseException:
            self._abort_start()
            raise
        finally:
            if thread is not None:
                _winapi.CloseHandle(thread)
            for descriptor in descriptors:
                try:
                    os.close(descriptor)
                except OSError:
                    pass

    def _abort_start(self):
        # An unassigned CMD has never resumed, and has no descendants. Only
        # this exact newly created suspended process can need direct cleanup.
        if self._process is not None and not self._assigned:
            try:
                _winapi.TerminateProcess(self._process, 1)
            except OSError:
                pass
        try:
            self.close()
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass

    def poll(self):
        if self.returncode is not None or self._process is None:
            return self.returncode
        result = _winapi.WaitForSingleObject(self._process, 0)
        if result == _winapi.WAIT_OBJECT_0:
            self.returncode = _winapi.GetExitCodeProcess(self._process)
        elif result != _winapi.WAIT_TIMEOUT:
            raise ValueError('无法核对本次 BAT 根进程状态')
        return self.returncode

    def wait(self, timeout=None):
        code = self.poll()
        if code is not None:
            return code
        if timeout is not None:
            timeout = float(timeout)
            if not math.isfinite(timeout):
                raise ValueError('BAT 等待时间必须为有限数值')
            deadline = time.monotonic() + max(0, timeout)
        else:
            deadline = None
        while True:
            milliseconds = (_winapi.INFINITE if deadline is None else
                min(60000, max(0, math.ceil((deadline-time.monotonic())*1000))))
            result = _winapi.WaitForSingleObject(self._process, milliseconds)
            if result == _winapi.WAIT_OBJECT_0:
                self.returncode = _winapi.GetExitCodeProcess(self._process)
                return self.returncode
            if result != _winapi.WAIT_TIMEOUT:
                raise ValueError('无法等待本次 BAT 根进程退出')
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(self.args, timeout)

    def job_process_ids(self):
        """Read the current job process list, including living descendants."""
        if self._job is None:
            return ()
        capacity = 16
        while capacity <= _MAX_JOB_PROCESSES:
            buffer = ctypes.create_string_buffer(8 + capacity*ctypes.sizeof(ctypes.c_size_t))
            returned = wintypes.DWORD()
            success = self.kernel.QueryInformationJobObject(self._job, _BASIC_PROCESS_ID_LIST,
                buffer, len(buffer), ctypes.byref(returned))
            error = ctypes.get_last_error() if not success else 0
            assigned, listed = struct.unpack_from('<II', buffer.raw)
            if success and listed == assigned and listed <= capacity:
                return struct.unpack_from(f'<{listed}Q', buffer.raw, 8) if listed else ()
            if not success and error != _ERROR_MORE_DATA:
                raise _failure('无法核对本次 BAT 子进程归属')
            capacity = max(capacity*2, assigned, listed)
        raise ValueError('本次 BAT 的进程数量超过归属核对上限')

    def has_live_processes(self):
        """Continue waiting for owned children after a BAT's CMD has exited."""
        return bool(self.job_process_ids())

    def owns(self, pid):
        """True only while the requested PID belongs to this live job."""
        return type(pid) is int and pid > 0 and pid in self.job_process_ids()

    def terminate(self):
        """Close only this job; never terminate processes found by name."""
        if self._job is not None:
            job = self._job
            _winapi.CloseHandle(job)
            self._job = None
        if self._process is not None:
            self.wait(timeout=10)

    def close(self):
        if self._closed:
            return
        try:
            self.terminate()
        finally:
            self._closed = True
            for stream in (self.stdin, self.stdout):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass
            if self._process is not None:
                _winapi.CloseHandle(self._process)
                self._process = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
