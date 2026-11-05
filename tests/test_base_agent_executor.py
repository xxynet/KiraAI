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


def test_default_session_messages_are_isolated_between_contexts():
    first = BaseAgentExecutionContext()
    second = BaseAgentExecutionContext()
    message = OpenAIMessage(role="assistant", content="first run")
    first.append_messages(message)
    assert first.messages == [message]
    assert first.messages[0] is message
    assert first.new_messages == [message]
    assert first.new_messages[0] is message
    assert second.messages == []
    assert second.new_messages == []
    assert first.messages is not second.messages
    assert first.new_messages is not second.new_messages
    assert first.messages is not first.new_messages


@pytest.mark.parametrize("context_type", [BaseAgentExecutionContext, AgentExecutionContext])
def test_context_preserves_explicit_session_message_list(context_type):
    existing = OpenAIMessage(role="user", content="incoming")
    messages = [OpenAIMessage(role="assistant", content="history"), existing]
    new_messages = [existing]
    kwargs = {"event": SimpleNamespace()} if context_type is AgentExecutionContext else {}
    context = context_type(messages=messages, new_messages=new_messages, **kwargs)
    message = OpenAIMessage(role="assistant", content="shared")
    context.append_messages(message)
    assert context.messages is messages
    assert context.new_messages is new_messages
    assert messages[-1] is new_messages[-1] is message
    assert [item.content for item in messages] == ["history", "incoming", "shared"]
    assert [item.content for item in new_messages] == ["incoming", "shared"]


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
    models = [_model(LLMResponse("complete"))]
    callback = AsyncMock()
    context = BaseAgentExecutionContext()
    request = LLMRequest(tool_set=tools)
    executor = PluginContext.create_agent_executor(
        Context(), models, context=context, request=request, config=config, on_result=callback,
    )

    assert executor.request.tool_set is tools
    assert not hasattr(executor, "tool_set")
    assert executor.config is config
    assert executor.model_group == models
    assert executor.on_result is callback
    assert executor.context is context
    assert executor.request is request


@pytest.mark.anyio
async def test_plugin_agent_runs_tools_and_fallback_without_event(no_event_hooks):
    manager = FuncToolManager(ToolExecutionConfig(max_tool_calls_per_step=0))
    im_tool = AsyncMock(return_value="must not run")
    manager.register_tool("probe", "", {}, im_tool)
    manager.execute_tools = AsyncMock(side_effect=AssertionError("Main agent execution must not be used"))
    plugin_ctx = SimpleNamespace(tool_mgr=manager)
    tools = ToolSet([ProbeTool()])
    config = AgentExecutionConfig(max_steps=2)
    primary = _model(ProviderAPIError("primary offline"), ProviderAPIError("primary offline"))
    fallback = _model(_tool_response(), LLMResponse("complete"))
    context = BaseAgentExecutionContext(
        messages=[OpenAIMessage(role="user", content="task")],
    )

    executor = PluginContext.create_agent_executor(plugin_ctx, [primary, fallback], request=LLMRequest(tool_set=tools), context=context, config=config)
    steps = [step async for step in executor.run()]

    assert isinstance(executor, BaseAgentExecutor)
    assert executor.config is config
    assert not hasattr(context, "event")
    assert [step.is_final for step in steps] == [False, True]
    assert all(isinstance(step, AgentStepResult) for step in steps)
    assert all(step.model is fallback.model for step in steps)
    assert [message.role for message in steps[-1].new_messages] == ["assistant", "tool", "assistant"]
    assert steps[-1].new_messages[1].content == "result: input"
    assert steps[-1].new_messages[-1].content == "complete"
    assert all(any(message is stored for stored in context.messages)
               for message in steps[-1].new_messages)
    final_request = fallback.chat.await_args.args[0]
    assert "final model call for this run" in final_request.messages[-2].content
    assert "<msg/>" not in final_request.messages[-2].content
    assert all("final model call" not in str(message.content) for message in context.messages)
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
    model = _model(_tool_response(), LLMResponse("complete"))
    context = BaseAgentExecutionContext()
    executor = PluginContext.create_agent_executor(SimpleNamespace(tool_mgr=manager), [model], context=context)

    steps = [step async for step in executor.run()]

    im_tool.assert_not_awaited()
    assert "not implemented" in steps[0].new_messages[1].content
    no_event_hooks.assert_not_called()


@pytest.mark.anyio
async def test_independent_agent_reports_provider_failure_without_im_exception_hook(no_event_hooks):
    model = _model(ProviderAPIError("provider unavailable"))
    context = BaseAgentExecutionContext()

    steps = [step async for step in BaseAgentExecutor([model], context=context).run()]

    assert len(steps) == 1
    assert steps[0].state == "error"
    assert steps[0].is_final
    assert "ProviderAPIError: provider unavailable" in steps[0].err
    assert steps[0].model is model.model
    no_event_hooks.assert_not_called()


@pytest.mark.parametrize("error", [TypeError("programming error"), asyncio.CancelledError()])
@pytest.mark.anyio
async def test_independent_agent_propagates_programming_errors_and_cancellation(no_event_hooks, error):
    model = _model(error)
    context = BaseAgentExecutionContext()

    with pytest.raises(type(error)):
        _ = [step async for step in BaseAgentExecutor([model], context=context).run()]

    assert context.messages == []
    no_event_hooks.assert_not_called()


@pytest.mark.anyio
async def test_independent_tools_obey_limits_without_event(no_event_hooks):
    class SlowTool(ProbeTool):
        async def execute(self, *, value):
            await asyncio.Event().wait()

    response = _tool_response()
    response.tool_calls += _tool_response(call_id="call-2").tool_calls
    model = _model(response)
    context = BaseAgentExecutionContext()
    config = AgentExecutionConfig(max_steps=1, tool_config=ToolExecutionConfig(
        max_tool_calls_per_step=1, tool_call_timeout=0.01, max_tool_output_tokens=32,
    ))
    executor = BaseAgentExecutor([model], request=LLMRequest(tool_set=ToolSet([SlowTool()])), context=context, config=config)

    steps = [step async for step in executor.run()]

    results = steps[0].llm_response.tool_results
    assert "timed out" in results[0]["content"]
    assert "limit exceeded" in results[1]["content"]
    assert all(len(result["content"].encode("utf-8")) <= 32 * 4 for result in results)
    assert len(steps[-1].new_messages[0].tool_calls) == 2
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
    child_context = BaseAgentExecutionContext()
    event = SimpleNamespace(sid="test:dm:parent", is_stopped=False)

    class DelegateTool(ProbeTool):
        name = "delegate"

        async def execute(self, current_event, *, value):
            assert current_event is event
            child = PluginContext.create_agent_executor(
                plugin_ctx, [child_model], request=LLMRequest(tool_set=child_tools), config=AgentExecutionConfig(max_steps=2),
                context=child_context,
            )
            result = None
            async for result in child.run():
                pass
            return result.llm_response.text_response

    parent_tools = ToolSet([DelegateTool()])
    parent_model = _model(_tool_response(name="delegate"), LLMResponse("parent complete"))
    parent_context = AgentExecutionContext(event=event)
    parent = AgentExecutor([parent_model], request=LLMRequest(tool_set=parent_tools), context=parent_context, config=AgentExecutionConfig(max_steps=2))

    steps = [step async for step in parent.run()]

    assert len(steps) == 2
    assert parent_context.messages[1].content == "child complete"
    assert parent_context.messages[-1].content == "parent complete"
    assert child_context.messages[1].content == "result: input"
    assert child_context.messages[-1].content == "child complete"
    assert parent_context.messages is not child_context.messages
    assert llm_hook.await_count == 2
    assert tool_hook.await_count == 1
    assert all(call.args[0] is event for call in llm_hook.await_args_list + tool_hook.await_args_list)
    assert not event.is_stopped


@pytest.mark.anyio
async def test_independent_executors_run_concurrently_without_sharing_history(no_event_hooks):
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
        messages=[OpenAIMessage(role="user", content=task)],
    ) for task in ("task A", "task B")]
    executors = [BaseAgentExecutor([model], context=context, config=AgentExecutionConfig(max_steps=1)) for context in contexts]

    async def run(executor):
        return [step async for step in executor.run()]

    results = await asyncio.wait_for(asyncio.gather(*(
        run(executor) for executor in executors
    )), timeout=2)

    assert [steps[0].llm_response.text_response for steps in results] == ["task A", "task B"]
    assert contexts[0].messages is not contexts[1].messages
    assert [context.messages[1].content for context in contexts] == ["task A", "task B"]
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
    context = AgentExecutionContext(event=event)
    executor = AgentExecutor([_model(response)], request=LLMRequest(tool_set=tools), context=context, config=AgentExecutionConfig(max_steps=1))

    steps = [step async for step in executor.run()]

    assert event.is_stopped
    assert calls == results == ["first", "second"]
    assert [result["tool_call_id"] for result in response.tool_results] == ["call-1"]
    assert [call["id"] for call in steps[0].assistant_message.tool_calls] == ["call-1"]
    assert [message.role for message in steps[-1].new_messages] == ["assistant", "tool"]
    assert steps[-1].new_messages[1].content == "first"


@pytest.mark.anyio
@pytest.mark.parametrize("replace_tool_set", [False, True])
async def test_model_and_tool_snapshots_refresh_only_when_next_background_turn_starts(no_event_hooks, replace_tool_set):
    tools = ToolSet()
    seen = []
    delivered = []

    class VersionTool(ProbeTool):
        def __init__(self, version):
            super().__init__()
            self.version = version

        def get_schema(self):
            schema = super().get_schema()
            schema["description"] = self.version
            return schema

        async def execute(self, *, value):
            return f"{self.version}:{value}"

    tools.add(VersionTool("old"))
    original, replacement = _model(), _model()
    original_calls = replacement_calls = 0

    async def original_chat(request):
        nonlocal original_calls
        original_calls += 1
        seen.append(("original", request.tools[0]["function"]["description"]))
        if original_calls == 1:
            executor.model_group = [replacement]
            if replace_tool_set:
                executor.request.tool_set = ToolSet([VersionTool("new")])
            else:
                tools.add(VersionTool("new"))
            return _tool_response()
        return LLMResponse("first complete")

    async def replacement_chat(request):
        nonlocal replacement_calls
        replacement_calls += 1
        seen.append(("replacement", request.tools[0]["function"]["description"]))
        return _tool_response() if replacement_calls == 1 else LLMResponse("second complete")

    async def on_result(result):
        delivered.append(result)
        if len(delivered) == 2:
            executor.queue("next turn")

    original.chat.side_effect = original_chat
    replacement.chat.side_effect = replacement_chat
    context = BaseAgentExecutionContext(messages=[OpenAIMessage(role="user", content="task")])
    executor = BaseAgentExecutor([original], request=LLMRequest(tool_set=tools), context=context, config=AgentExecutionConfig(max_steps=2), on_result=on_result)
    history = context.messages
    final = await executor.start()

    assert final is delivered[-1]
    assert seen == [("original", "old"), ("original", "old"), ("replacement", "new"), ("replacement", "new")]
    assert delivered[0].llm_response.tool_results[0]["content"] == "old:input"
    assert delivered[2].llm_response.tool_results[0]["content"] == "new:input"
    assert context.messages is history
    assert all("final model call" not in str(message.content) for message in history)
    assert not hasattr(context, "request")
    assert not hasattr(context, "model_group")
    assert context.new_messages is final.new_messages
    assert delivered[1].new_messages is not final.new_messages
    no_event_hooks.assert_not_called()


@pytest.mark.anyio
@pytest.mark.parametrize("driver", ["run", "start"])
async def test_prepared_request_preserves_options_with_one_history_and_tool_source(no_event_hooks, driver):
    from core.prompt_manager import Prompt

    tools = ToolSet([ProbeTool()])
    model = _model(_tool_response(), LLMResponse("follow-up complete"))
    context = BaseAgentExecutionContext(messages=[OpenAIMessage(role="user", content="current history")])
    request = LLMRequest(
        messages=[OpenAIMessage(role="user", content="stale request history")],
        user_prompt=[Prompt("user metadata")], system_prompt=[Prompt("system metadata")],
        tool_set=tools,
        tool_choice="required",
    )
    request.tools = [{"type": "function", "function": {"name": "unavailable"}}]

    executor = BaseAgentExecutor([model], context=context, request=request, config=AgentExecutionConfig(max_steps=1))
    steps = [step async for step in executor.run()] if driver == "run" else [await executor.start()]

    sent = model.chat.await_args.args[0]
    assert sent is not request
    assert sent.tool_choice == "required"
    assert sent.user_prompt == request.user_prompt and sent.user_prompt is not request.user_prompt
    assert sent.system_prompt == request.system_prompt and sent.system_prompt is not request.system_prompt
    assert sent.tools == tools.to_list()
    assert sent.tool_set is not request.tool_set
    assert sent.tool_set.tools == request.tool_set.tools
    assert request.tools[0]["function"]["name"] == "unavailable"
    assert sent.messages[0].content == "current history"
    assert all(message.content != "stale request history" for message in context.messages)
    assert steps[0].llm_response.tool_results[0]["content"] == "result: input"
    assert [message.content for message in request.messages] == ["stale request history"]
    assert all("final model call" not in str(message.content) for message in context.messages)

    request.tool_choice = "auto"
    request.user_prompt.append(Prompt("updated metadata"))
    follow_up = await executor.queue("next task")
    next_request = model.chat.await_args.args[0]
    assert executor.context is context
    assert executor.request is request
    assert next_request is not sent and next_request is not request
    assert next_request.tool_choice == "auto" and sent.tool_choice == "required"
    assert next_request.user_prompt == request.user_prompt
    assert len(sent.user_prompt) == 1
    assert next_request.system_prompt == request.system_prompt
    assert next_request.tools == tools.to_list()
    assert [message.role for message in next_request.messages[:3]] == ["user", "assistant", "tool"]
    assert follow_up.new_messages is context.new_messages
    assert [message.content for message in follow_up.new_messages] == ["next task", "follow-up complete"]
    assert [message.content for message in request.messages] == ["stale request history"]
    assert all("final model call" not in str(message.content) for message in context.messages)
    no_event_hooks.assert_not_called()
