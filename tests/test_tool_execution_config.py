from copy import deepcopy
from dataclasses import FrozenInstanceError
from unittest.mock import Mock

import pytest
from fastapi import FastAPI

from core.agent.config import ToolExecutionConfig
from core.agent.func_tool_manager import FuncToolManager
from core.config.default import DEFAULT_CONFIG
from core.config.tool_execution import build_tool_execution_config
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
