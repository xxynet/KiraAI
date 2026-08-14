import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from core.plugin.builtin_plugins.file.main import BackgroundExecTask, FilePlugin


class FakeBackgroundProcess:
    def __init__(self, stdout: str = "", stderr: str = "", delay: float = 0):
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stdout.feed_data(stdout.encode())
        self.stdout.feed_eof()
        self.stderr.feed_data(stderr.encode())
        self.stderr.feed_eof()
        self.delay = delay
        self.pid = 12345
        self.returncode = None
        self._stopped = asyncio.Event()

    async def wait(self):
        if self.returncode is None and self.delay:
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=self.delay)
            except asyncio.TimeoutError:
                self.returncode = 0
        elif self.returncode is None:
            self.returncode = 0
        return self.returncode

    def terminate(self):
        self.returncode = -15
        self._stopped.set()

    def kill(self):
        self.terminate()


@pytest.fixture
def file_plugin():
    plugin = FilePlugin.__new__(FilePlugin)
    plugin.allowed_exec_sessions = ["test:dm:1"]
    plugin.exec_deny_list = []
    plugin._exec_timeout = 30
    plugin._background_exec_timeout = 30
    plugin._background_exec_wait_seconds = 2
    plugin._background_exec_tasks = {}
    plugin._background_notice_tasks = set()
    return plugin


@pytest.mark.anyio
async def test_initialize_loads_exec_timeouts():
    plugin = FilePlugin(
        None,
        {
            "exec_timeout": 10,
            "background_exec_timeout": 60,
            "background_exec_wait_seconds": 3,
        },
    )

    await plugin.initialize()

    assert plugin._exec_timeout == 10
    assert plugin._background_exec_timeout == 60
    assert plugin._background_exec_wait_seconds == 3


@pytest.mark.anyio
async def test_filter_tools_enables_background_manager_with_exec(file_plugin):
    file_plugin.plugin_cfg = {"enabled_tools": ["exec"]}
    tool_set = SimpleNamespace(remove=Mock())
    request = SimpleNamespace(tool_set=tool_set)

    await file_plugin.filter_tools(SimpleNamespace(), request)

    disabled_tools = set(tool_set.remove.call_args.args)
    assert "exec" not in disabled_tools
    assert "manage_background_exec" not in disabled_tools


@pytest.mark.anyio
async def test_filter_tools_disables_background_manager_without_exec(file_plugin):
    file_plugin.plugin_cfg = {"enabled_tools": ["read_file"]}
    tool_set = SimpleNamespace(remove=Mock())
    request = SimpleNamespace(tool_set=tool_set)

    await file_plugin.filter_tools(SimpleNamespace(), request)

    disabled_tools = set(tool_set.remove.call_args.args)
    assert {"exec", "manage_background_exec"} <= disabled_tools


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
    assert run.call_args.kwargs["timeout"] == 30


@pytest.mark.anyio
async def test_exec_rejects_missing_work_dir(file_plugin, tmp_path):
    event = SimpleNamespace(sid="test:dm:1")
    missing_dir = tmp_path / "missing"

    with patch("core.plugin.builtin_plugins.file.main.subprocess.run") as run:
        result = await file_plugin.exec(event, "echo test", str(missing_dir))

    assert result == f"Working directory not found: {missing_dir}"
    run.assert_not_called()


@pytest.mark.anyio
async def test_exec_background_returns_immediate_result_when_command_finishes_quickly(file_plugin):
    event = SimpleNamespace(sid="test:dm:1")
    file_plugin._background_exec_timeout = 45
    process = FakeBackgroundProcess(stdout="ok")

    with patch(
        "core.plugin.builtin_plugins.file.main.asyncio.create_subprocess_shell",
        new=AsyncMock(return_value=process),
    ):
        result = await file_plugin.exec(event, "echo test", background=True)

    assert result == "Shell command output:\nok"
    assert file_plugin._background_exec_tasks == {}


@pytest.mark.anyio
async def test_exec_background_publishes_result_after_wait_timeout(file_plugin):
    event = SimpleNamespace(sid="test:dm:1")
    file_plugin.ctx = SimpleNamespace(publish_notice=AsyncMock())
    file_plugin._background_exec_wait_seconds = 0.01
    process = FakeBackgroundProcess(stdout="finished", delay=0.05)

    with patch(
        "core.plugin.builtin_plugins.file.main.asyncio.create_subprocess_shell",
        new=AsyncMock(return_value=process),
    ):
        result = await file_plugin.exec(event, "echo test", background=True)

    assert "Shell command is running in the background (task_id: exec-" in result
    for _ in range(10):
        if file_plugin.ctx.publish_notice.await_count:
            break
        await asyncio.sleep(0.02)

    file_plugin.ctx.publish_notice.assert_awaited_once()
    args = file_plugin.ctx.publish_notice.await_args
    assert args.args[0] == event.sid
    assert args.kwargs["is_mentioned"] is True
    assert "Background shell command completed (task_id: exec-" in args.args[1][0].text
    assert "Shell command output:\nfinished" in args.args[1][0].text


@pytest.mark.anyio
async def test_manage_background_exec_lists_output_and_stops_own_task(file_plugin):
    event = SimpleNamespace(sid="test:dm:1")
    file_plugin.ctx = SimpleNamespace(publish_notice=AsyncMock())
    file_plugin._background_exec_wait_seconds = 0.01
    process = FakeBackgroundProcess(stdout="started\n", delay=1)

    async def terminate_process(fake_process):
        fake_process.terminate()
        await fake_process.wait()

    with patch(
        "core.plugin.builtin_plugins.file.main.asyncio.create_subprocess_shell",
        new=AsyncMock(return_value=process),
    ), patch.object(
        file_plugin,
        "_terminate_background_process",
        new=AsyncMock(side_effect=terminate_process),
    ):
        result = await file_plugin.exec(event, "echo test", background=True)
        task_id = result.split("task_id: ", maxsplit=1)[1].split(")", maxsplit=1)[0]

        await asyncio.sleep(0)
        listed = await file_plugin.manage_background_exec(event, "list")
        output = await file_plugin.manage_background_exec(event, "output", task_id)
        stopped = await file_plugin.manage_background_exec(event, "stop", task_id)

    assert task_id in listed
    assert "started" in output
    assert stopped == f"Stop requested for background task {task_id}."
    for _ in range(10):
        if task_id not in file_plugin._background_exec_tasks:
            break
        await asyncio.sleep(0.01)

    assert task_id not in file_plugin._background_exec_tasks
    file_plugin.ctx.publish_notice.assert_not_awaited()


@pytest.mark.anyio
async def test_background_exec_stop_before_wait_returns_captured_output(file_plugin, tmp_path):
    background_task = BackgroundExecTask(
        task_id="exec-test",
        session="test:dm:1",
        work_dir=tmp_path,
        timeout=30,
        stop_requested=True,
    )
    process = FakeBackgroundProcess(stdout="started\n", delay=1)

    async def terminate_process(fake_process):
        fake_process.terminate()
        await fake_process.wait()

    with patch(
        "core.plugin.builtin_plugins.file.main.asyncio.create_subprocess_shell",
        new=AsyncMock(return_value=process),
    ), patch.object(
        file_plugin,
        "_terminate_background_process",
        new=AsyncMock(side_effect=terminate_process),
    ):
        result = await file_plugin._run_background_shell_command(
            "echo test", background_task, {}
        )

    assert result == "Shell command stopped by request:\nstarted\n"


@pytest.mark.anyio
async def test_cancelled_background_exec_cleans_up_task(file_plugin):
    event = SimpleNamespace(sid="test:dm:1")
    file_plugin.ctx = SimpleNamespace(publish_notice=AsyncMock())
    file_plugin._background_exec_wait_seconds = 1
    process = FakeBackgroundProcess(delay=0.05)

    with patch(
        "core.plugin.builtin_plugins.file.main.asyncio.create_subprocess_shell",
        new=AsyncMock(return_value=process),
    ):
        exec_call = asyncio.create_task(file_plugin.exec(event, "echo test", background=True))
        for _ in range(10):
            if file_plugin._background_exec_tasks:
                break
            await asyncio.sleep(0)
        exec_call.cancel()
        with pytest.raises(asyncio.CancelledError):
            await exec_call
        await asyncio.sleep(0.1)

    assert file_plugin._background_exec_tasks == {}
    file_plugin.ctx.publish_notice.assert_not_awaited()


@pytest.mark.anyio
async def test_terminate_stops_and_clears_background_tasks(file_plugin):
    event = SimpleNamespace(sid="test:dm:1")
    file_plugin.ctx = SimpleNamespace(publish_notice=AsyncMock())
    file_plugin._background_exec_wait_seconds = 0.01
    process = FakeBackgroundProcess(delay=1)

    async def terminate_process(fake_process):
        fake_process.terminate()
        await fake_process.wait()

    with patch(
        "core.plugin.builtin_plugins.file.main.asyncio.create_subprocess_shell",
        new=AsyncMock(return_value=process),
    ), patch.object(
        file_plugin,
        "_terminate_background_process",
        new=AsyncMock(side_effect=terminate_process),
    ):
        result = await file_plugin.exec(event, "echo test", background=True)
        assert "task_id: exec-" in result
        await file_plugin.terminate()

    assert process.returncode == -15
    assert file_plugin._background_exec_tasks == {}
    assert file_plugin._background_notice_tasks == set()
    file_plugin.ctx.publish_notice.assert_not_awaited()
