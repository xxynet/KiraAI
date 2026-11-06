from copy import deepcopy
from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI

from core.agent.config import ToolExecutionConfig
from core.agent.func_tool_manager import FuncToolManager
from core.config.default import DEFAULT_CONFIG
from core.config.tool_execution import build_tool_execution_config
from core.provider import LLMResponse
from webui.routes.config import ConfigRoutes


class AppConfig(dict):
    def get_config(self, key, default=None):
        value = self
        for part in key.split("."):
            if not isinstance(value, dict) or part not in value:
                return default
            value = value[part]
        return value

    def save_config(self):
        pass


def test_defaults_are_independent_and_immutable():
    first, second = FuncToolManager(), FuncToolManager()
    assert first.config == ToolExecutionConfig()
    assert first.config is not second.config
    with pytest.raises(FrozenInstanceError):
        first.config.tool_call_timeout = 10


@pytest.mark.parametrize("field,value", [
    ("max_tool_calls_per_step", -1), ("max_tool_calls_per_step", True),
    ("max_tool_calls_per_step", 1.5), ("max_tool_output_tokens", -1),
    ("max_tool_output_tokens", False), ("max_tool_output_tokens", "10"),
    ("tool_call_timeout", 0), ("tool_call_timeout", -1),
    ("tool_call_timeout", True), ("tool_call_timeout", "10"),
    ("tool_call_timeout", float("inf")), ("tool_call_timeout", float("nan")),
])
def test_direct_config_rejects_invalid_limits(field, value):
    with pytest.raises(ValueError, match=field):
        ToolExecutionConfig(**{field: value})


@pytest.mark.parametrize("raw,expected", [
    ({}, ToolExecutionConfig()),
    ({"max_tool_calls_per_turn": "3", "tool_call_timeout": "2.5", "max_tool_output_tokens": 0},
     ToolExecutionConfig(max_tool_calls_per_step=3, tool_call_timeout=2.5, max_tool_output_tokens=0)),
    ({"max_tool_calls_per_turn": -1, "tool_call_timeout": -1},
     ToolExecutionConfig(max_tool_calls_per_step=0, tool_call_timeout=None)),
    ({"tool_call_timeout": 0}, ToolExecutionConfig(tool_call_timeout=None)),
    ({"max_tool_calls_per_turn": "bad", "tool_call_timeout": "bad", "max_tool_output_tokens": True},
     ToolExecutionConfig()),
    ({"max_tool_calls_per_turn": float("inf"), "tool_call_timeout": float("nan")},
     ToolExecutionConfig()),
])
def test_application_settings_are_normalized_without_mutation(raw, expected):
    config = AppConfig(bot_config={"agent": raw})
    assert build_tool_execution_config(config) == expected
    assert config["bot_config"]["agent"] is raw


@pytest.mark.anyio
async def test_configuration_api_does_not_access_tool_manager():
    config = AppConfig(deepcopy(DEFAULT_CONFIG))

    class Lifecycle:
        kira_config = config

        @property
        def tool_manager(self):
            raise AssertionError("Configuration routes must not access tool_manager")

    routes = ConfigRoutes(FastAPI(), Lifecycle())
    config.save_config = Mock()
    payload = deepcopy(config["bot_config"])
    payload["agent"] = {"max_tool_calls_per_turn": "2", "tool_call_timeout": 0, "max_tool_output_tokens": 4}
    await routes.update_configuration({"bot_config": payload})
    assert config["bot_config"] == payload
    config.save_config.assert_called_once()

    await routes.update_configuration({"locale": {"lang": "en"}})
    assert config["bot_config"] == payload


@pytest.mark.anyio
@pytest.mark.parametrize("method", ["execute_tool", "execute_tools"])
async def test_deprecated_execution_refreshes_config_between_calls(monkeypatch, method):
    from core.plugin.handlers import event_handler_reg

    monkeypatch.setattr(event_handler_reg, "get_handlers", lambda *args, **kwargs: [])
    config = AppConfig(bot_config={"agent": {"max_tool_calls_per_turn": 2}})
    resolve = Mock(side_effect=lambda: build_tool_execution_config(config))
    manager = FuncToolManager(config=resolve)
    tool = AsyncMock(return_value="done")
    manager.register_tool("probe", "", {}, tool)

    async def execute(override=None):
        response = LLMResponse("", tool_calls=[{
            "id": "call-1", "function": {"name": "probe", "arguments": "{}"},
        }])
        args = (SimpleNamespace(is_stopped=False), response) if method == "execute_tool" else (response,)
        with pytest.warns(DeprecationWarning):
            await getattr(manager, method)(*args, tool_set=manager.build_tool_set(), config=override)
        return response

    await execute()
    assert tool.await_count == 1
    assert resolve.call_count == 1
    config["bot_config"]["agent"].update({
        "max_tool_calls_per_turn": 0, "tool_call_timeout": 3, "max_tool_output_tokens": 8,
    })
    response = await execute()
    assert tool.await_count == 1
    assert response.tool_results
    assert resolve.call_count == 2

    await execute(ToolExecutionConfig(max_tool_calls_per_step=1))
    assert tool.await_count == 2
    assert resolve.call_count == 2
    assert manager.config == ToolExecutionConfig(
        max_tool_calls_per_step=0, tool_call_timeout=3, max_tool_output_tokens=8,
    )

    manager.config = ToolExecutionConfig(max_tool_calls_per_step=1)
    await execute()
    assert tool.await_count == 3


@pytest.mark.anyio
async def test_deprecated_execution_keeps_one_config_snapshot_per_batch():
    config = AppConfig(bot_config={"agent": {"max_tool_calls_per_turn": 2}})
    resolve = Mock(side_effect=lambda: build_tool_execution_config(config))
    manager = FuncToolManager(resolve)

    async def change_settings():
        config["bot_config"]["agent"]["max_tool_calls_per_turn"] = 0
        return "done"

    tool = AsyncMock(side_effect=change_settings)
    manager.register_tool("probe", "", {}, tool)
    response = LLMResponse("", tool_calls=[
        {"id": f"call-{index}", "function": {"name": "probe", "arguments": "{}"}}
        for index in range(2)
    ])
    with pytest.warns(DeprecationWarning):
        await manager.execute_tools(response, manager.build_tool_set())
    assert tool.await_count == 2
    assert resolve.call_count == 1
    assert len(response.tool_results) == 2
