import os
import subprocess
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core.plugin.builtin_plugins.file import main as file_main
from core.plugin.builtin_plugins.file.main import FilePlugin, is_restricted_path


@pytest.fixture
def file_plugin():
    plugin = FilePlugin.__new__(FilePlugin)
    plugin.allowed_sessions = ["test:dm:1"]
    plugin.allowed_exec_sessions = ["test:dm:1"]
    plugin.allowed_read_paths = ("data/files",)
    plugin.allowed_write_paths = ("data/files",)
    plugin.exec_deny_list = []
    plugin._exec_timeout = 30
    return plugin


@pytest.mark.parametrize("path", [
    "data/files/monkey.txt",
    "data/files/tokenizer.py",
    "data/files/keyboard_notes.md",
    "data/files/donkey/notes.txt",
    "data/files/passwordless_setup.txt",
])
def test_legitimate_paths_are_not_restricted(path):
    assert is_restricted_path(path) is False


@pytest.mark.parametrize("path", [
    "~/.ssh/id_rsa",
    "~/.gnupg/secring.gpg",
    "~/.aws/credentials",
    "~/.config/gh/hosts.yml",
    "/home/user/.ssh/config",
    "data/files/server.pem",
    "data/files/bundle.p12",
    "data/files/id_rsa.key",
    "data/files/api_key.txt",
    "data/files/secrets/db.txt",
    "data/files/access-token.json",
    "data/files/my.password",
])
def test_sensitive_paths_are_restricted(path):
    assert is_restricted_path(path) is True


@pytest.mark.anyio
async def test_read_file_allows_filename_containing_key_substring(file_plugin, tmp_path, monkeypatch):
    monkeypatch.setattr(file_main, "get_data_path", lambda: tmp_path)
    target = tmp_path / "files" / "monkey.txt"
    target.parent.mkdir(parents=True)
    target.write_text("banana\n", encoding="utf-8")

    result = await file_plugin.read_file(
        SimpleNamespace(sid="test:dm:1"), "data/files/monkey.txt"
    )

    assert result == "banana\n"


@pytest.mark.anyio
async def test_read_file_still_denies_key_material(file_plugin, tmp_path, monkeypatch):
    monkeypatch.setattr(file_main, "get_data_path", lambda: tmp_path)

    result = await file_plugin.read_file(
        SimpleNamespace(sid="test:dm:1"), "data/files/service_key.txt"
    )

    assert result == "Permission denied: Path contains restricted keywords"


# ─── Foreground exec process group ───────────────────────────────────────────


class FakeTimedOutProcess:
    def __init__(self):
        self.pid = 4242
        self.returncode = None
        self.communicate_calls = 0

    def communicate(self, timeout=None):
        self.communicate_calls += 1
        if self.returncode is None:
            raise subprocess.TimeoutExpired("cmd", timeout or 0)
        return "", ""

    def wait(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired("cmd", timeout or 0)
        return self.returncode

    def kill(self):
        self.returncode = -9

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def test_foreground_exec_creates_its_own_process_group(tmp_path):
    with patch("core.plugin.builtin_plugins.file.main.subprocess.Popen") as popen:
        popen.return_value.__enter__.return_value.communicate.return_value = ("ok", "")
        popen.return_value.__enter__.return_value.returncode = 0

        result = FilePlugin._run_shell_command("echo test", 30, {}, tmp_path)

    assert result == "Shell command output:\nok"
    kwargs = popen.call_args.kwargs
    assert kwargs["cwd"] == tmp_path
    assert kwargs.get("start_new_session") is True


def test_foreground_exec_timeout_kills_the_whole_process_group(tmp_path, monkeypatch):
    process = FakeTimedOutProcess()
    killed = []

    def killpg(pid, sig):
        killed.append((pid, sig))
        if sig == getattr(file_main.signal, "SIGKILL", 9):
            process.returncode = -9

    monkeypatch.setattr(file_main, "PROCESS_TERMINATION_GRACE_SECONDS", 0.01)
    with patch("core.plugin.builtin_plugins.file.main.os.name", "posix"), patch(
        "core.plugin.builtin_plugins.file.main.os.killpg", side_effect=killpg, create=True
    ), patch(
        "core.plugin.builtin_plugins.file.main.subprocess.Popen", return_value=process
    ):
        result = FilePlugin._run_shell_command("sleep 60", 1, {}, tmp_path)

    assert result == "Shell command timed out after 1 seconds: sleep 60"
    assert killed == [
        (process.pid, file_main.signal.SIGTERM),
        (process.pid, getattr(file_main.signal, "SIGKILL", 9)),
    ]


@pytest.mark.skipif(os.name == "nt", reason="POSIX process groups")
def test_timeout_does_not_leave_orphaned_grandchildren(tmp_path):
    marker = tmp_path / "alive.txt"
    # A detached grandchild that outlives the shell unless the whole group is killed.
    command = (
        f'(for i in $(seq 1 100); do echo x >> "{marker}"; sleep 0.1; done) '
        '>/dev/null 2>&1 & sleep 30'
    )

    result = FilePlugin._run_shell_command(command, 1, dict(os.environ), tmp_path)

    assert "timed out after 1 seconds" in result
    size_at_kill = marker.stat().st_size if marker.exists() else 0
    time.sleep(0.5)
    assert (marker.stat().st_size if marker.exists() else 0) == size_at_kill
