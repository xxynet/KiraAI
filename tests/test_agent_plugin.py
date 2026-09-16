import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from core.plugin.builtin_plugins.agent import main as agent_main
from core.plugin.builtin_plugins.agent.main import BackgroundExecTask, AgentPlugin


@pytest.fixture(autouse=True)
def isolated_plugin_config_dir(tmp_path, monkeypatch):
    """Keep plugin config reads/writes away from the real data directory."""
    config_root = tmp_path / "config"
    monkeypatch.setattr(agent_main, "get_config_path", lambda: config_root)
    return config_root


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


class ResistantProcess:
    """Fake process that stays alive until it is explicitly killed or exits.

    Unlike ``FakeBackgroundProcess``, ``kill()`` is distinguishable from a
    spontaneous exit, so a test can tell whether the code had to force it.
    """

    def __init__(self):
        self.pid = 12345
        self.returncode = None
        self._finished = asyncio.Event()
        self.killed = False
        self.wait_count = 0

    async def wait(self):
        self.wait_count += 1
        await self._finished.wait()
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9
        self._finished.set()

    def exit(self, returncode: int = 0):
        """Simulate the process exiting on its own, e.g. after a working taskkill."""
        self.returncode = returncode
        self._finished.set()


class FakeKillerProcess:
    def __init__(self, returncode: int):
        self.returncode = returncode

    async def wait(self):
        return self.returncode


@pytest.fixture
def agent_plugin():
    plugin = AgentPlugin.__new__(AgentPlugin)
    plugin.file_permission_mode = "allow_list"
    plugin.file_sessions = ["test:dm:1"]
    plugin.exec_permission_mode = "allow_list"
    plugin.exec_sessions = ["test:dm:1"]
    plugin.exec_command_deny_list = []
    plugin._exec_timeout = 30
    plugin._background_exec_timeout = 30
    plugin._background_exec_wait_seconds = 2
    plugin._background_exec_tasks = {}
    plugin._background_notice_tasks = set()
    return plugin


@pytest.mark.anyio
async def test_initialize_loads_exec_timeouts():
    plugin = AgentPlugin(
        None,
        {
            "exec_access": {
                "timeout": 10,
                "background_timeout": 60,
                "background_wait_seconds": 3,
            },
        },
    )

    await plugin.initialize()

    assert plugin._exec_timeout == 10
    assert plugin._background_exec_timeout == 60
    assert plugin._background_exec_wait_seconds == 3


@pytest.mark.anyio
async def test_initialize_loads_sectioned_permissions_and_paths():
    plugin = AgentPlugin(
        None,
        {
            "file_access": {
                "permission_mode": "deny_list",
                "session_list": ["dc:dm:1"],
                "extra_read_paths": ["E:/read"],
                "extra_write_paths": ["E:/write"],
            },
            "exec_access": {
                "permission_mode": "DENY_LIST",
                "session_list": ["tg:dm:2"],
                "command_deny_list": ["rm -rf"],
            },
        },
    )

    await plugin.initialize()

    assert plugin.file_permission_mode == "deny_list"
    assert plugin.file_sessions == ["dc:dm:1"]
    assert plugin.exec_permission_mode == "deny_list"
    assert plugin.exec_sessions == ["tg:dm:2"]
    assert plugin.exec_command_deny_list == ["rm -rf"]
    assert "E:/read" in plugin.allowed_read_paths
    assert "E:/write" in plugin.allowed_write_paths
    assert "E:/write" not in plugin.allowed_read_paths
    assert "data/files" in plugin.allowed_read_paths


@pytest.mark.anyio
async def test_initialize_falls_back_to_allow_list_for_an_unknown_mode():
    plugin = AgentPlugin(None, {"file_access": {"permission_mode": "nonsense"}})

    await plugin.initialize()

    assert plugin.file_permission_mode == "allow_list"


@pytest.mark.anyio
async def test_initialize_ignores_malformed_sections_and_session_entries():
    plugin = AgentPlugin(
        None,
        {
            "file_access": ["not", "a", "section"],
            "exec_access": {
                "session_list": ["dc:dm:1", 42, None, "  ", True],
            },
        },
    )

    await plugin.initialize()

    assert plugin.file_sessions == []
    assert plugin.file_permission_mode == "allow_list"
    assert plugin.exec_sessions == ["dc:dm:1", "42"]
    assert plugin._exec_timeout == 30


def test_session_permission_allow_list_grants_only_listed_sessions(agent_plugin):
    agent_plugin.file_permission_mode = "allow_list"
    agent_plugin.file_sessions = ["dc:dm:1"]

    assert agent_plugin._is_file_session_allowed("dc:dm:1") is True
    assert agent_plugin._is_file_session_allowed("dc:dm:2") is False


def test_session_permission_allow_list_grants_nobody_without_sessions(agent_plugin):
    agent_plugin.exec_permission_mode = "allow_list"
    agent_plugin.exec_sessions = []

    assert agent_plugin._is_exec_session_allowed("dc:dm:1") is False


def test_session_permission_deny_list_grants_every_other_session(agent_plugin):
    agent_plugin.file_permission_mode = "deny_list"
    agent_plugin.file_sessions = ["dc:dm:1"]

    assert agent_plugin._is_file_session_allowed("dc:dm:1") is False
    assert agent_plugin._is_file_session_allowed("dc:dm:2") is True


def test_session_permission_deny_list_grants_everybody_without_sessions(agent_plugin):
    agent_plugin.exec_permission_mode = "deny_list"
    agent_plugin.exec_sessions = []

    assert agent_plugin._is_exec_session_allowed("dc:dm:1") is True


def test_file_and_exec_permissions_are_independent(agent_plugin):
    agent_plugin.file_permission_mode = "allow_list"
    agent_plugin.file_sessions = ["dc:dm:1"]
    agent_plugin.exec_permission_mode = "allow_list"
    agent_plugin.exec_sessions = ["tg:dm:2"]

    assert agent_plugin._is_file_session_allowed("dc:dm:1") is True
    assert agent_plugin._is_exec_session_allowed("dc:dm:1") is False
    assert agent_plugin._is_file_session_allowed("tg:dm:2") is False
    assert agent_plugin._is_exec_session_allowed("tg:dm:2") is True


@pytest.mark.anyio
async def test_read_file_is_denied_for_a_listed_session_in_deny_list_mode(
    agent_plugin, tmp_path, monkeypatch
):
    monkeypatch.setattr(agent_main, "restricted_paths", [])
    agent_plugin.file_permission_mode = "deny_list"
    agent_plugin.file_sessions = ["test:dm:1"]
    agent_plugin.allowed_read_paths = (str(tmp_path),)
    target = tmp_path / "note.txt"
    target.write_text("hello", encoding="utf-8")

    denied = await agent_plugin.read_file(SimpleNamespace(sid="test:dm:1"), str(target))
    allowed = await agent_plugin.read_file(SimpleNamespace(sid="test:dm:9"), str(target))

    assert denied == "Permission denied: current session not allowed to access local files"
    assert allowed == "hello"


@pytest.mark.anyio
async def test_exec_is_denied_by_deny_list_session_permission(agent_plugin):
    agent_plugin.exec_permission_mode = "deny_list"
    agent_plugin.exec_sessions = ["test:dm:1"]

    result = await agent_plugin.exec(SimpleNamespace(sid="test:dm:1"), "echo test")

    assert result == "Permission denied: current session not allowed to execute shell commands"


@pytest.mark.anyio
async def test_filter_tools_enables_background_manager_with_exec(agent_plugin):
    agent_plugin.plugin_cfg = {"tools": {"enabled_tools": ["exec"]}}
    tool_set = SimpleNamespace(remove=Mock())
    request = SimpleNamespace(tool_set=tool_set)

    await agent_plugin.filter_tools(SimpleNamespace(), request)

    disabled_tools = set(tool_set.remove.call_args.args)
    assert "exec" not in disabled_tools
    assert "manage_background_exec" not in disabled_tools


@pytest.mark.anyio
async def test_filter_tools_disables_background_manager_without_exec(agent_plugin):
    agent_plugin.plugin_cfg = {"tools": {"enabled_tools": ["read_file"]}}
    tool_set = SimpleNamespace(remove=Mock())
    request = SimpleNamespace(tool_set=tool_set)

    await agent_plugin.filter_tools(SimpleNamespace(), request)

    disabled_tools = set(tool_set.remove.call_args.args)
    assert {"exec", "manage_background_exec"} <= disabled_tools


@pytest.mark.anyio
async def test_exec_uses_resolved_work_dir(agent_plugin, tmp_path):
    event = SimpleNamespace(sid="test:dm:1")
    completed = SimpleNamespace(stdout="ok", stderr="", returncode=0)

    with patch(
        "core.plugin.builtin_plugins.agent.main.subprocess.run",
        return_value=completed,
    ) as run:
        result = await agent_plugin.exec(event, "echo test", str(tmp_path))

    assert result == "Shell command output:\nok"
    assert run.call_args.kwargs["cwd"] == tmp_path.resolve()
    assert run.call_args.kwargs["timeout"] == 30


@pytest.mark.anyio
async def test_exec_rejects_missing_work_dir(agent_plugin, tmp_path):
    event = SimpleNamespace(sid="test:dm:1")
    missing_dir = tmp_path / "missing"

    with patch("core.plugin.builtin_plugins.agent.main.subprocess.run") as run:
        result = await agent_plugin.exec(event, "echo test", str(missing_dir))

    assert result == f"Working directory not found: {missing_dir}"
    run.assert_not_called()


@pytest.mark.anyio
async def test_exec_background_returns_immediate_result_when_command_finishes_quickly(agent_plugin):
    event = SimpleNamespace(sid="test:dm:1")
    agent_plugin._background_exec_timeout = 45
    process = FakeBackgroundProcess(stdout="ok")

    with patch(
        "core.plugin.builtin_plugins.agent.main.asyncio.create_subprocess_shell",
        new=AsyncMock(return_value=process),
    ):
        result = await agent_plugin.exec(event, "echo test", background=True)

    assert result == "Shell command output:\nok"
    assert agent_plugin._background_exec_tasks == {}


@pytest.mark.anyio
async def test_exec_background_publishes_result_after_wait_timeout(agent_plugin):
    event = SimpleNamespace(sid="test:dm:1")
    agent_plugin.ctx = SimpleNamespace(publish_notice=AsyncMock())
    agent_plugin._background_exec_wait_seconds = 0.01
    process = FakeBackgroundProcess(stdout="finished", delay=0.05)

    with patch(
        "core.plugin.builtin_plugins.agent.main.asyncio.create_subprocess_shell",
        new=AsyncMock(return_value=process),
    ):
        result = await agent_plugin.exec(event, "echo test", background=True)

    assert "Shell command is running in the background (task_id: exec-" in result
    for _ in range(10):
        if agent_plugin.ctx.publish_notice.await_count:
            break
        await asyncio.sleep(0.02)

    agent_plugin.ctx.publish_notice.assert_awaited_once()
    args = agent_plugin.ctx.publish_notice.await_args
    assert args.args[0] == event.sid
    assert args.kwargs["is_mentioned"] is True
    assert "Background shell command completed (task_id: exec-" in args.args[1][0].text
    assert "Shell command output:\nfinished" in args.args[1][0].text


@pytest.mark.anyio
async def test_manage_background_exec_lists_output_and_stops_own_task(agent_plugin):
    event = SimpleNamespace(sid="test:dm:1")
    agent_plugin.ctx = SimpleNamespace(publish_notice=AsyncMock())
    agent_plugin._background_exec_wait_seconds = 0.01
    process = FakeBackgroundProcess(stdout="started\n", delay=1)

    async def terminate_process(fake_process):
        fake_process.terminate()
        await fake_process.wait()

    with patch(
        "core.plugin.builtin_plugins.agent.main.asyncio.create_subprocess_shell",
        new=AsyncMock(return_value=process),
    ), patch.object(
        agent_plugin,
        "_terminate_background_process",
        new=AsyncMock(side_effect=terminate_process),
    ):
        result = await agent_plugin.exec(event, "echo test", background=True)
        task_id = result.split("task_id: ", maxsplit=1)[1].split(")", maxsplit=1)[0]

        await asyncio.sleep(0)
        listed = await agent_plugin.manage_background_exec(event, "list")
        output = await agent_plugin.manage_background_exec(event, "output", task_id)
        stopped = await agent_plugin.manage_background_exec(event, "stop", task_id)

    assert task_id in listed
    assert "started" in output
    assert stopped == f"Stop requested for background task {task_id}."
    for _ in range(10):
        if task_id not in agent_plugin._background_exec_tasks:
            break
        await asyncio.sleep(0.01)

    assert task_id not in agent_plugin._background_exec_tasks
    agent_plugin.ctx.publish_notice.assert_not_awaited()


@pytest.mark.anyio
async def test_background_exec_stop_before_wait_returns_captured_output(agent_plugin, tmp_path):
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
        "core.plugin.builtin_plugins.agent.main.asyncio.create_subprocess_shell",
        new=AsyncMock(return_value=process),
    ), patch.object(
        agent_plugin,
        "_terminate_background_process",
        new=AsyncMock(side_effect=terminate_process),
    ):
        result = await agent_plugin._run_background_shell_command(
            "echo test", background_task, {}
        )

    assert result == "Shell command stopped by request:\nstarted\n"


@pytest.mark.anyio
async def test_cancelled_background_exec_cleans_up_task(agent_plugin):
    event = SimpleNamespace(sid="test:dm:1")
    agent_plugin.ctx = SimpleNamespace(publish_notice=AsyncMock())
    agent_plugin._background_exec_wait_seconds = 1
    process = FakeBackgroundProcess(delay=1)

    async def terminate_process(fake_process):
        fake_process.terminate()
        await fake_process.wait()

    with patch(
        "core.plugin.builtin_plugins.agent.main.asyncio.create_subprocess_shell",
        new=AsyncMock(return_value=process),
    ), patch.object(
        agent_plugin,
        "_terminate_background_process",
        new=AsyncMock(side_effect=terminate_process),
    ):
        exec_call = asyncio.create_task(agent_plugin.exec(event, "echo test", background=True))
        for _ in range(10):
            if agent_plugin._background_exec_tasks:
                break
            await asyncio.sleep(0)
        exec_call.cancel()
        with pytest.raises(asyncio.CancelledError):
            await exec_call

    assert process.returncode == -15
    assert agent_plugin._background_exec_tasks == {}
    agent_plugin.ctx.publish_notice.assert_not_awaited()


@pytest.mark.anyio
async def test_terminate_stops_and_clears_background_tasks(agent_plugin):
    event = SimpleNamespace(sid="test:dm:1")
    agent_plugin.ctx = SimpleNamespace(publish_notice=AsyncMock())
    agent_plugin._background_exec_wait_seconds = 0.01
    process = FakeBackgroundProcess(delay=1)

    async def terminate_process(fake_process):
        fake_process.terminate()
        await fake_process.wait()

    with patch(
        "core.plugin.builtin_plugins.agent.main.asyncio.create_subprocess_shell",
        new=AsyncMock(return_value=process),
    ), patch.object(
        agent_plugin,
        "_terminate_background_process",
        new=AsyncMock(side_effect=terminate_process),
    ):
        result = await agent_plugin.exec(event, "echo test", background=True)
        assert "task_id: exec-" in result
        await agent_plugin.terminate()

    assert process.returncode == -15
    assert agent_plugin._background_exec_tasks == {}
    assert agent_plugin._background_notice_tasks == set()
    agent_plugin.ctx.publish_notice.assert_not_awaited()


@pytest.mark.anyio
async def test_terminate_background_process_force_kills_posix_process_group(monkeypatch):
    process = ResistantProcess()
    signals = []
    sigkill = getattr(agent_main.signal, "SIGKILL", 9)

    def killpg(pid, signal_value):
        signals.append((pid, signal_value))
        if signal_value == sigkill:
            process.returncode = -9
            process._finished.set()

    monkeypatch.setattr(agent_main, "PROCESS_TERMINATION_GRACE_SECONDS", 0.01)
    monkeypatch.setattr(agent_main.signal, "SIGKILL", sigkill, raising=False)
    with patch("core.plugin.builtin_plugins.agent.main.os.name", "posix"), patch(
        "core.plugin.builtin_plugins.agent.main.os.killpg",
        side_effect=killpg,
        create=True,
    ):
        await AgentPlugin._terminate_background_process(process)

    assert signals == [
        (process.pid, agent_main.signal.SIGTERM),
        (process.pid, sigkill),
    ]


@pytest.mark.anyio
async def test_terminate_background_process_kills_when_taskkill_fails():
    process = ResistantProcess()
    killer = FakeKillerProcess(returncode=1)
    exec_mock = AsyncMock(return_value=killer)

    with patch("core.plugin.builtin_plugins.agent.main.os.name", "nt"), patch(
        "core.plugin.builtin_plugins.agent.main.asyncio.create_subprocess_exec",
        new=exec_mock,
    ):
        await AgentPlugin._terminate_background_process(process)

    exec_mock.assert_awaited_once()
    assert exec_mock.await_args.args == (
        "taskkill", "/PID", str(process.pid), "/T", "/F",
    )
    # taskkill reported failure, so the shell process itself had to be killed
    assert process.killed is True
    assert process.returncode == -9
    # Killed as soon as taskkill failed: the process must not be waited on until
    # the grace period expires, which would be a second wait() call
    assert process.wait_count == 1


@pytest.mark.anyio
async def test_terminate_background_process_accepts_taskkill_success():
    process = ResistantProcess()
    killer = FakeKillerProcess(returncode=0)

    async def run_taskkill(*_, **__):
        # A successful taskkill takes the process down with it
        process.exit(returncode=0)
        return killer

    exec_mock = AsyncMock(side_effect=run_taskkill)

    with patch("core.plugin.builtin_plugins.agent.main.os.name", "nt"), patch(
        "core.plugin.builtin_plugins.agent.main.asyncio.create_subprocess_exec",
        new=exec_mock,
    ):
        await AgentPlugin._terminate_background_process(process)

    assert exec_mock.await_count == 1
    assert process.killed is False
    assert process.returncode == 0
    assert process.wait_count == 1
