import asyncio
import ctypes
import os
import subprocess
import sys
from contextlib import contextmanager
from ctypes import wintypes
from pathlib import Path

from core.plugin import logger

PROCESS_TERMINATE = 0x0001
PROCESS_SET_QUOTA = 0x0100
_LAUNCHER_PATH = Path(__file__).with_name("windows_shell_launcher.py")


if os.name == "nt":
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
    _kernel32.TerminateJobObject.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _kernel32.CloseHandle.restype = wintypes.BOOL


@contextmanager
def _command_job(pid: int):
    job = _kernel32.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        process = _kernel32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid)
        if not process:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not _kernel32.AssignProcessToJobObject(job, process):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            _kernel32.CloseHandle(process)
        try:
            yield
        except BaseException:
            if not _kernel32.TerminateJobObject(job, 1):
                error = ctypes.WinError(ctypes.get_last_error())
                logger.error(f"Failed to terminate Windows shell job for process {pid}: {error}")
            raise
    finally:
        _kernel32.CloseHandle(job)


class _ShellOutput(asyncio.SubprocessProtocol):
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.closed = loop.create_future()
        self.output = {1: bytearray(), 2: bytearray()}
        self.error: Exception | None = None

    def pipe_data_received(self, fd: int, data: bytes):
        self.output[fd].extend(data)

    def pipe_connection_lost(self, fd: int, exc: Exception | None):
        if exc is not None and self.error is None:
            self.error = exc

    def connection_lost(self, exc: Exception | None):
        self.closed.set_result(exc or self.error)

    def text(self, fd: int) -> str:
        return self.output[fd].decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")


async def run_windows_shell_command(
    command: str, timeout: int, env: dict[str, str], cwd: Path,
) -> subprocess.CompletedProcess[str]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    # A Windows venv redirector can spawn the interpreter before we attach it.
    # Only the internal launcher uses the base interpreter.
    transport, output = await loop.subprocess_exec(
        lambda: _ShellOutput(loop),
        sys._base_executable, "-I", "-S", "-B", _LAUNCHER_PATH,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=env, cwd=cwd,
    )
    try:
        with _command_job(transport.get_pid()):
            if loop.time() >= deadline:
                raise subprocess.TimeoutExpired(command, timeout)
            stdin = transport.get_pipe_transport(0)
            stdin.write(command.encode("utf-8", "surrogatepass"))
            stdin.close()
            # The timeout covers both process exit and pipe EOF. Close the
            # transport on timeout instead of waiting for a second pipe drain.
            done, _ = await asyncio.wait((output.closed,), timeout=deadline - loop.time())
            if not done:
                raise subprocess.TimeoutExpired(command, timeout)
            if error := output.closed.result():
                raise error
        return subprocess.CompletedProcess(command, transport.get_returncode(), output.text(1), output.text(2))
    finally:
        transport.close()
