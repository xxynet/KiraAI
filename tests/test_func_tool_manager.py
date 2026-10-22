from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from core.agent.agent_executor import AgentExecutor
from core.agent.func_tool_manager import FuncToolManager
from core.agent.mcp_mgr import MCPManager
from core.agent.tool import ToolResult, truncate_tool_output
from core.provider import LLMResponse
from core.utils.media_refs import MEDIA_REF_TYPE


@pytest.mark.parametrize("text", ["", "plain text", "中文🙂", "a" * 256, "🙂" * 64])
def test_output_at_or_below_budget_is_unchanged(text):
    assert truncate_tool_output(text, 64) == text


@pytest.mark.parametrize("text", ["A" * 10000, "中文🙂" * 1000])
@pytest.mark.parametrize("budget", [1, 2, 3, 16, 64, 128])
def test_truncation_bounds_single_line_and_unicode_output(text, budget):
    output = truncate_tool_output(text, budget)

    assert len(output.encode("utf-8")) <= budget * 4
    assert output != text
    assert "\ufffd" not in output
    assert "truncated" in output or "[..]" in output


def test_truncation_preserves_head_tail_and_explains_how_to_get_more():
    text = "BEGIN\n" + "x" * 10000 + "\nEND"

    output = truncate_tool_output(text, 128)

    assert output.startswith("BEGIN\n")
    assert output.endswith("\nEND")
    assert f"original size: {len(text.encode('utf-8'))} UTF-8 bytes" in output
    assert "Narrow the query or request a smaller range" in output


def test_zero_budget_disables_truncation():
    text = "中文🙂" * 10000
    assert truncate_tool_output(text, 0) == text


def _response():
    response = LLMResponse("")
    response.tool_calls = [
        {"id": "call-1", "function": {"name": "probe", "arguments": "{}"}},
    ]
    return response


@pytest.fixture
def tool_environment(monkeypatch):
    from core.agent import func_tool_manager
    from core.plugin.handlers import event_handler_reg

    config = {
        "bot_config.agent.max_tool_calls_per_turn": 5,
        "bot_config.agent.tool_call_timeout": 60,
        "bot_config.agent.max_tool_output_tokens": 128,
    }
    manager = FuncToolManager(SimpleNamespace(get_config=config.get))
    event = SimpleNamespace(is_stopped=False)
    monkeypatch.setattr(event_handler_reg, "get_handlers", lambda *args, **kwargs: [])
    log = Mock()
    monkeypatch.setattr(func_tool_manager.tool_logger, "info", log)
    return manager, event, config, log


@pytest.mark.anyio
@pytest.mark.parametrize("result_kind", ["string", "tool_result", "mcp"])
async def test_all_tool_text_is_truncated_before_logging_and_context(tool_environment, result_kind):
    manager, event, _, log = tool_environment
    text = "BEGIN\n" + "private-middle-" * 1000 + "\nEND"
    if result_kind == "tool_result":
        result = ToolResult(text=text)
    elif result_kind == "mcp":
        result = MCPManager._parse_tool_result({"content": [{"type": "text", "text": text}]})
    else:
        result = text
    manager.register_tool("probe", "", {}, AsyncMock(return_value=result))
    response = _response()

    await manager.execute_tool(event, response, manager.build_tool_set())

    output = response.tool_results[0]["content"]
    assert output.startswith("BEGIN\n") and output.endswith("\nEND")
    assert "Tool output truncated" in output
    assert len(output.encode("utf-8")) <= 128 * 4
    assert log.call_args.args == (f"tool_result: {output}",)
    assert all(text not in str(call) for call in log.call_args_list)
    messages = AgentExecutor._build_tool_messages(response.tool_results)
    assert messages[0].content == output
    assert messages[0].tool_call_id == "call-1"


@pytest.mark.anyio
async def test_hook_text_is_bounded_and_media_and_attachment_paths_survive(
    tool_environment, monkeypatch, tmp_path
):
    from core.plugin.handlers import event_handler_reg

    manager, event, config, _ = tool_environment
    config["bot_config.agent.max_tool_output_tokens"] = 256
    path = str(tmp_path / "attachment.png").replace("\\", "/")
    attachment = SimpleNamespace(to_path=AsyncMock(return_value=path))
    ref = {"type": MEDIA_REF_TYPE, "path": "session_media/a/b.png", "mime_type": "image/png"}
    result = ToolResult(text="short", attachments=[attachment], media_refs=[ref])

    async def expand_result(event, result):
        result.text += "hook-output-" * 2000

    handler = SimpleNamespace(exec_handler=expand_result)
    monkeypatch.setattr(event_handler_reg, "get_handlers", lambda *args, **kwargs: [handler])
    manager.register_tool("probe", "", {}, AsyncMock(return_value=result))
    response = _response()

    await manager.execute_tool(event, response, manager.build_tool_set())

    parts = response.tool_results[0]["content"]
    assert len(parts[0]["text"].encode("utf-8")) <= 256 * 4
    assert "Tool output truncated" in parts[0]["text"]
    assert path in parts[0]["text"]
    assert parts[1] is ref
    messages = AgentExecutor._build_tool_messages(response.tool_results)
    assert messages[1].content[1] is ref
    attachment.to_path.assert_awaited_once()


@pytest.mark.anyio
async def test_budget_applies_per_call_and_config_changes_take_effect(tool_environment):
    manager, event, config, _ = tool_environment
    text = "x" * 2000
    manager.register_tool("probe", "", {}, AsyncMock(return_value=text))
    response = _response()
    response.tool_calls.append(
        {"id": "call-2", "function": {"name": "probe", "arguments": "{}"}}
    )

    await manager.execute_tool(event, response, manager.build_tool_set())

    assert len(response.tool_results) == 2
    assert all(len(result["content"].encode("utf-8")) <= 128 * 4 for result in response.tool_results)
    config["bot_config.agent.max_tool_output_tokens"] = 0
    response = _response()
    await manager.execute_tool(event, response, manager.build_tool_set())
    assert response.tool_results[0]["content"] == text


@pytest.mark.anyio
@pytest.mark.parametrize("value", [None, "invalid", -1, float("inf"), 0.5, False, True])
async def test_invalid_budget_uses_default(tool_environment, value):
    manager, event, config, _ = tool_environment
    config["bot_config.agent.max_tool_output_tokens"] = value
    manager.register_tool("probe", "", {}, AsyncMock(return_value="x" * 80000))
    response = _response()

    await manager.execute_tool(event, response, manager.build_tool_set())

    output = response.tool_results[0]["content"]
    assert "Tool output truncated" in output
    assert len(output.encode("utf-8")) <= 10000 * 4
    assert len(output.encode("utf-8")) > 9000 * 4


@pytest.mark.anyio
async def test_missing_budget_uses_default_and_short_results_stay_unchanged(tool_environment):
    manager, event, config, _ = tool_environment
    del config["bot_config.agent.max_tool_output_tokens"]
    execute = AsyncMock(side_effect=["x" * 80000, "small result"])
    manager.register_tool("probe", "", {}, execute)

    response = _response()
    await manager.execute_tool(event, response, manager.build_tool_set())
    assert "Tool output truncated" in response.tool_results[0]["content"]
    assert len(response.tool_results[0]["content"].encode("utf-8")) <= 40000

    response = _response()
    await manager.execute_tool(event, response, manager.build_tool_set())
    assert response.tool_results[0]["content"] == "small result"


@pytest.mark.anyio
async def test_oversized_tool_errors_are_also_truncated(tool_environment):
    manager, event, _, _ = tool_environment
    manager.register_tool("probe", "", {}, AsyncMock(side_effect=RuntimeError("x" * 5000)))
    response = _response()

    await manager.execute_tool(event, response, manager.build_tool_set())

    output = response.tool_results[0]["content"]
    assert "Tool output truncated" in output
    assert len(output.encode("utf-8")) <= 128 * 4


@pytest.mark.anyio
async def test_tool_call_limit_messages_obey_output_budget(tool_environment):
    manager, event, config, _ = tool_environment
    config["bot_config.agent.max_tool_output_tokens"] = 1
    config["bot_config.agent.max_tool_calls_per_turn"] = 1
    manager.register_tool("probe", "", {}, AsyncMock(return_value="long output"))
    response = _response()
    response.tool_calls.append(
        {"id": "call-2", "function": {"name": "probe", "arguments": "{}"}}
    )

    await manager.execute_tool(event, response, manager.build_tool_set())

    assert len(response.tool_results) == 2
    assert all(len(result["content"].encode("utf-8")) <= 4 for result in response.tool_results)
