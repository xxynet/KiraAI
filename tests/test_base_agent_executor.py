import asyncio
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import AsyncMock, Mock

import pytest

from core.agent.agent_executor import (
    AgentExecutionContext,
    AgentExecutor,
    AgentStepResult,
)
from core.agent.base_agent_executor import BaseAgentExecutionContext, BaseAgentExecutor
from core.agent.config import AgentExecutionConfig, ToolExecutionConfig
from core.agent.func_tool_manager import FuncToolManager
from core.agent.message import OpenAIMessage
from core.agent.tool import ToolResult, ToolSet
from core.plugin.handlers import EventType, event_handler_reg
from core.plugin.plugin_context import PluginContext
from core.provider import (
    LLMModelClient,
    LLMRequest,
    LLMResponse,
    ModelInfo,
    ModelType,
    ProviderAPIError,
)
from core.utils.tool_utils import BaseTool


def _model(*responses):
    model = LLMModelClient(ModelInfo(
        model_type=ModelType.LLM, model_id="test", model_name="test-model",
        provider_id="test", provider_name="Test Provider",
    ))
    model.chat = AsyncMock(side_effect=responses)
    return model


def test_default_new_messages_are_isolated_between_contexts():
    first = BaseAgentExecutionContext(request=LLMRequest(), model_group=[])
    second = BaseAgentExecutionContext(request=LLMRequest(), model_group=[])
    message = OpenAIMessage(role="assistant", content="first run")

    first.append_messages(message)

    assert first.new_messages == [message]
    assert first.request.messages[0] is message
    assert first.new_messages[0] is message
    assert second.new_messages == []
    assert second.request.messages == []
    assert first.new_messages is not second.new_messages


@pytest.mark.parametrize("context_type", [BaseAgentExecutionContext, AgentExecutionContext])
def test_context_preserves_explicit_shared_message_list(context_type):
    messages = []
    kwargs = {"event": SimpleNamespace()} if context_type is AgentExecutionContext else {}
    context = context_type(request=LLMRequest(), model_group=[], new_messages=messages, **kwargs)
    message = OpenAIMessage(role="assistant", content="shared")

    context.append_messages(message)

    assert context.new_messages is messages
    assert messages == [message]
    assert context.request.messages[0] is message


def _tool_response(name="probe", arguments='{"value": "input"}', call_id="call-1"):
    return LLMResponse("", tool_calls=[{
        "id": call_id, "type": "function",
        "function": {"name": name, "arguments": arguments},
    }])


class ProbeTool(BaseTool):
    name = "probe"
    description = "Return a value."
    parameters: ClassVar[dict] = {"type": "object", "properties": {"value": {"type": "string"}}}

    async def execute(self, *, value):
        return ToolResult(text=f"result: {value}")


@pytest.fixture
def no_event_hooks(monkeypatch):
    hooks = Mock(side_effect=AssertionError("Independent agents must not access IM hooks"))
    monkeypatch.setattr(event_handler_reg, "get_handlers", hooks)
    return hooks


def test_plugin_agent_factory_uses_explicit_tools_without_main_manager():
    class Context:
        @property
        def tool_mgr(self):
            raise AssertionError("Independent agents must not access the main agent tool manager")

    tools = ToolSet([ProbeTool()])
    config = AgentExecutionConfig(max_steps=2)
    executor = PluginContext.create_agent_executor(Context(), tools, config=config)

    assert executor.tool_set is tools
    assert executor.config is config


@pytest.mark.anyio
async def test_plugin_agent_runs_tools_and_fallback_without_event(no_event_hooks):
    manager = FuncToolManager(ToolExecutionConfig(max_tool_calls_per_step=0))
    im_tool = AsyncMock(return_value="must not run")
    manager.register_tool("probe", "", {}, im_tool)
    manager.execute_tools = AsyncMock(side_effect=AssertionError("Main agent execution must not be used"))
    plugin_ctx = SimpleNamespace(tool_mgr=manager)
    tools = ToolSet([ProbeTool()])
    config = AgentExecutionConfig(max_steps=2)
    executor = PluginContext.create_agent_executor(plugin_ctx, tools, config=config)
    primary = _model(ProviderAPIError("primary offline"), ProviderAPIError("primary offline"))
    fallback = _model(_tool_response(), LLMResponse("complete"))
    context = BaseAgentExecutionContext(
        request=LLMRequest(messages=[{"role": "user", "content": "task"}], tool_set=tools),
        model_group=[primary, fallback],
    )

    steps = [step async for step in executor.run(context)]

    assert isinstance(executor, BaseAgentExecutor)
    assert executor.config is config
    assert not hasattr(context, "event")
    assert [step.is_final for step in steps] == [False, True]
    assert all(isinstance(step, AgentStepResult) for step in steps)
    assert all(step.model is fallback.model for step in steps)
    assert [message.role for message in context.new_messages] == ["assistant", "tool", "assistant"]
    assert context.new_messages[1].content == "result: input"
    assert context.new_messages[-1].content == "complete"
    assert all(any(message is stored for stored in context.request.messages)
               for message in context.new_messages)
    assert "final model call for this run" in context.request.messages[-2].content
    assert "<msg/>" not in context.request.messages[-2].content
    assert manager.config == ToolExecutionConfig(max_tool_calls_per_step=0)
    assert "probe" in manager.tool_set
    manager.execute_tools.assert_not_awaited()
    im_tool.assert_not_awaited()
    no_event_hooks.assert_not_called()


@pytest.mark.anyio
async def test_independent_agent_does_not_inherit_registered_im_tools(no_event_hooks):
    manager = FuncToolManager()
    im_tool = AsyncMock(return_value="must not run")
    manager.register_tool("probe", "", {}, im_tool)
    executor = PluginContext.create_agent_executor(SimpleNamespace(tool_mgr=manager))
    context = BaseAgentExecutionContext(
        request=LLMRequest(),
        model_group=[_model(_tool_response(), LLMResponse("complete"))],
    )

    steps = [step async for step in executor.run(context)]

    im_tool.assert_not_awaited()
    assert "not implemented" in steps[0].new_messages[1].content
    no_event_hooks.assert_not_called()


@pytest.mark.anyio
async def test_independent_agent_reports_provider_failure_without_im_exception_hook(no_event_hooks):
    model = _model(ProviderAPIError("provider unavailable"))
    context = BaseAgentExecutionContext(request=LLMRequest(), model_group=[model])

    steps = [step async for step in BaseAgentExecutor().run(context)]

    assert len(steps) == 1
    assert steps[0].state == "error"
    assert steps[0].is_final
    assert "ProviderAPIError: provider unavailable" in steps[0].err
    assert steps[0].model is model.model
    no_event_hooks.assert_not_called()


@pytest.mark.parametrize("error", [TypeError("programming error"), asyncio.CancelledError()])
@pytest.mark.anyio
async def test_independent_agent_propagates_programming_errors_and_cancellation(no_event_hooks, error):
    context = BaseAgentExecutionContext(request=LLMRequest(), model_group=[_model(error)])

    with pytest.raises(type(error)):
        _ = [step async for step in BaseAgentExecutor().run(context)]

    assert context.new_messages == []
    no_event_hooks.assert_not_called()


@pytest.mark.anyio
async def test_independent_tools_obey_limits_without_event(no_event_hooks):
    class SlowTool(ProbeTool):
        async def execute(self, *, value):
            await asyncio.Event().wait()

    response = _tool_response()
    response.tool_calls += _tool_response(call_id="call-2").tool_calls
    context = BaseAgentExecutionContext(request=LLMRequest(), model_group=[_model(response)])
    config = AgentExecutionConfig(max_steps=1, tool_config=ToolExecutionConfig(
        max_tool_calls_per_step=1, tool_call_timeout=0.01, max_tool_output_tokens=32,
    ))
    executor = BaseAgentExecutor(ToolSet([SlowTool()]), config=config)

    steps = [step async for step in executor.run(context)]

    results = steps[0].llm_response.tool_results
    assert "timed out" in results[0]["content"]
    assert "limit exceeded" in results[1]["content"]
    assert all(len(result["content"].encode("utf-8")) <= 32 * 4 for result in results)
    assert len(context.new_messages[0].tool_calls) == 2
    no_event_hooks.assert_not_called()


@pytest.mark.anyio
async def test_parent_im_tool_can_run_child_agent_with_separate_history(monkeypatch):
    llm_hook = AsyncMock()
    tool_hook = AsyncMock()
    hooks = {
        EventType.ON_LLM_RESPONSE: [SimpleNamespace(exec_handler=llm_hook)],
        EventType.ON_TOOL_RESULT: [SimpleNamespace(exec_handler=tool_hook)],
    }
    monkeypatch.setattr(event_handler_reg, "get_handlers", lambda event_type: hooks.get(event_type, []))
    manager = FuncToolManager()
    plugin_ctx = SimpleNamespace(tool_mgr=manager)
    child_tools = ToolSet([ProbeTool()])
    child_model = _model(_tool_response(), LLMResponse("child complete"))
    child_context = BaseAgentExecutionContext(request=LLMRequest(tool_set=child_tools), model_group=[child_model])
    event = SimpleNamespace(sid="test:dm:parent", is_stopped=False)

    class DelegateTool(ProbeTool):
        name = "delegate"

        async def execute(self, current_event, *, value):
            assert current_event is event
            child = PluginContext.create_agent_executor(
                plugin_ctx, config=AgentExecutionConfig(max_steps=2),
            )
            result = None
            async for result in child.run(child_context):
                pass
            return result.llm_response.text_response

    parent_tools = ToolSet([DelegateTool()])
    parent_model = _model(_tool_response(name="delegate"), LLMResponse("parent complete"))
    parent_context = AgentExecutionContext(event, LLMRequest(tool_set=parent_tools), [], [parent_model])
    parent = AgentExecutor(parent_tools, config=AgentExecutionConfig(max_steps=2))

    steps = [step async for step in parent.run(parent_context)]

    assert len(steps) == 2
    assert parent_context.new_messages[1].content == "child complete"
    assert parent_context.new_messages[-1].content == "parent complete"
    assert child_context.new_messages[1].content == "result: input"
    assert child_context.new_messages[-1].content == "child complete"
    assert parent_context.request is not child_context.request
    assert parent_context.new_messages is not child_context.new_messages
    assert llm_hook.await_count == 2
    assert tool_hook.await_count == 1
    assert all(call.args[0] is event for call in llm_hook.await_args_list + tool_hook.await_args_list)
    assert not event.is_stopped


@pytest.mark.anyio
async def test_independent_runs_share_executor_without_sharing_history(no_event_hooks):
    model = _model()
    both_started = asyncio.Event()
    requests = []

    async def respond(request):
        requests.append(request)
        if len(requests) == 2:
            both_started.set()
        await both_started.wait()
        return LLMResponse(request.messages[0].content)

    model.chat.side_effect = respond
    contexts = [BaseAgentExecutionContext(
        request=LLMRequest(messages=[{"role": "user", "content": task}]), model_group=[model],
    ) for task in ("task A", "task B")]
    executor = BaseAgentExecutor(config=AgentExecutionConfig(max_steps=1))

    async def run(context):
        return [step async for step in executor.run(context)]

    results = await asyncio.wait_for(asyncio.gather(*(run(context) for context in contexts)), timeout=2)

    assert [steps[0].llm_response.text_response for steps in results] == ["task A", "task B"]
    assert contexts[0].request is not contexts[1].request
    assert contexts[0].new_messages is not contexts[1].new_messages
    assert [context.new_messages[0].content for context in contexts] == ["task A", "task B"]
    no_event_hooks.assert_not_called()


@pytest.mark.anyio
async def test_im_tool_hook_stops_batch_and_keeps_only_answered_calls(monkeypatch):
    event = SimpleNamespace(sid="test:dm:parent", is_stopped=False)
    calls = []
    results = []

    class EventTool(ProbeTool):
        async def execute(self, current_event, *, value):
            assert current_event is event
            calls.append(value)
            return value

    async def on_result(current_event, result):
        assert current_event is event
        results.append(result.text)
        if len(results) == 2:
            current_event.is_stopped = True

    monkeypatch.setattr(event_handler_reg, "get_handlers", lambda event_type: (
        [SimpleNamespace(exec_handler=on_result)] if event_type == EventType.ON_TOOL_RESULT else []
    ))
    response = _tool_response(arguments='{"value": "first"}')
    response.tool_calls += _tool_response(arguments='{"value": "second"}', call_id="call-2").tool_calls
    response.tool_calls += _tool_response(arguments='{"value": "third"}', call_id="call-3").tool_calls
    tools = ToolSet([EventTool()])
    context = AgentExecutionContext(event, LLMRequest(tool_set=tools), [], [_model(response)])
    executor = AgentExecutor(tools, config=AgentExecutionConfig(max_steps=1))

    steps = [step async for step in executor.run(context)]

    assert event.is_stopped
    assert calls == results == ["first", "second"]
    assert [result["tool_call_id"] for result in response.tool_results] == ["call-1"]
    assert [call["id"] for call in steps[0].assistant_message.tool_calls] == ["call-1"]
    assert [message.role for message in context.new_messages] == ["assistant", "tool"]
    assert context.new_messages[1].content == "first"
