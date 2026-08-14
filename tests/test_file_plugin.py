from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core.plugin.builtin_plugins.file.main import FilePlugin


@pytest.fixture
def file_plugin():
    plugin = FilePlugin.__new__(FilePlugin)
    plugin.allowed_exec_sessions = ["test:dm:1"]
    plugin.exec_deny_list = []
    return plugin


@pytest.mark.anyio
async def test_exec_uses_resolved_work_dir(file_plugin, tmp_path):
    event = SimpleNamespace(sid="test:dm:1")
    completed = SimpleNamespace(stdout="ok", stderr="", returncode=0)

    with patch(
        "core.plugin.builtin_plugins.file.main.subprocess.run",
        return_value=completed,
    ) as run:
        result = await file_plugin.exec(event, "echo test", str(tmp_path))

    assert result == "Shell command output:\nok"
    assert run.call_args.kwargs["cwd"] == tmp_path.resolve()


@pytest.mark.anyio
async def test_exec_rejects_missing_work_dir(file_plugin, tmp_path):
    event = SimpleNamespace(sid="test:dm:1")
    missing_dir = tmp_path / "missing"

    with patch("core.plugin.builtin_plugins.file.main.subprocess.run") as run:
        result = await file_plugin.exec(event, "echo test", str(missing_dir))

    assert result == f"Working directory not found: {missing_dir}"
    run.assert_not_called()
