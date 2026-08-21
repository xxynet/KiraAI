"""Tests for tool-call and config robustness against null/missing values."""

import pytest

from core.agent.func_tool_manager import FuncToolManager
from core.agent.tool import ToolSet
from core.message_manager import _config_float, _config_int
from core.provider import LLMResponse
from core.utils.tool_utils import BaseTool


class RecordingTool(BaseTool):
    """A tool whose name is only set in __init__, like plugin-provided tools."""

    def __init__(self, name: str = "no_arg_tool"):
        super().__init__()
        self.name = name
        self.description = "records the kwargs it was called with"
        self.parameters = {"type": "object", "properties": {}}
        self.calls = []

    async def execute(self, event=None, **kwargs):
        self.calls.append(kwargs)
        return "ok"

    def get_schema(self):
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


class StaticNameTool(BaseTool):
    name = "static_tool"
    description = "declares its name on the class"
    parameters = {}

    async def execute(self, *args, **kwargs):
        return "ok"


class FakeConfig:
    def __init__(self, values: dict = None):
        self.values = values or {}

    def get_config(self, key, default=None):
        return self.values.get(key, default)


class FakeEvent:
    is_stopped = False


def _tool_call(arguments, name="no_arg_tool", call_id="call_1"):
    function = {"name": name}
    if arguments is not _MISSING:
        function["arguments"] = arguments
    return {"id": call_id, "function": function}


_MISSING = object()


# ====== ToolSet.add ======

def test_add_class_whose_name_is_set_in_init():
    """add() must compare the instantiated tool's name: a class that only sets
    `name` in __init__ has no class-level attribute to read."""
    tool_set = ToolSet()
    tool_set.add(StaticNameTool())

    tool_set.add(RecordingTool)

    assert [t.name for t in tool_set.tools] == ["static_tool", "no_arg_tool"]


def test_add_replaces_tool_with_same_name():
    tool_set = ToolSet()
    first = RecordingTool()
    second = RecordingTool()
    tool_set.add(first)
    tool_set.add(second)

    assert tool_set.tools == [second]
    assert "no_arg_tool" in tool_set


# ====== execute_tool argument parsing ======

@pytest.mark.anyio
@pytest.mark.parametrize("arguments", [None, "", "   ", _MISSING])
async def test_missing_tool_arguments_are_treated_as_empty(arguments):
    """Providers may omit `arguments` for no-arg tool calls; that must not
    raise AttributeError/TypeError before the tool is even called."""
    tool = RecordingTool()
    tool_set = ToolSet(tools=[tool])
    manager = FuncToolManager(FakeConfig())

    resp = LLMResponse("", tool_calls=[_tool_call(arguments)])
    await manager.execute_tool(FakeEvent(), resp, tool_set=tool_set)

    assert tool.calls == [{}]
    assert resp.tool_results[0]["content"] == "ok"


@pytest.mark.anyio
async def test_malformed_tool_arguments_are_reported_and_ignored():
    tool = RecordingTool()
    tool_set = ToolSet(tools=[tool])
    manager = FuncToolManager(FakeConfig())

    resp = LLMResponse("", tool_calls=[_tool_call("{not json")])
    await manager.execute_tool(FakeEvent(), resp, tool_set=tool_set)

    assert tool.calls == [{}]


@pytest.mark.anyio
@pytest.mark.parametrize("value", [None, "", "abc", {}])
async def test_null_tool_call_limits_fall_back_to_defaults(value):
    """A null max_tool_calls_per_turn must not break tool execution."""
    tool = RecordingTool()
    tool_set = ToolSet(tools=[tool])
    manager = FuncToolManager(FakeConfig({
        "bot_config.agent.max_tool_calls_per_turn": value,
        "bot_config.agent.tool_call_timeout": value,
    }))

    resp = LLMResponse("", tool_calls=[_tool_call('{"x": 1}')])
    await manager.execute_tool(FakeEvent(), resp, tool_set=tool_set)

    assert tool.calls == [{"x": 1}]


# ====== config coercion ======

@pytest.mark.parametrize(
    "value,expected",
    [(None, 2), ("", 2), ("abc", 2), ({}, 2), (5, 5), ("7", 7), (3.9, 3)],
)
def test_config_int_falls_back_on_invalid_values(value, expected):
    assert _config_int(value, 2) == expected


@pytest.mark.parametrize(
    "value,expected",
    [(None, 1.5), ("", 1.5), ("abc", 1.5), ([], 1.5), (2, 2.0), ("0.8", 0.8)],
)
def test_config_float_falls_back_on_invalid_values(value, expected):
    assert _config_float(value, 1.5) == expected
