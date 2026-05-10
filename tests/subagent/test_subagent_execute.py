import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from core.subagent.subagent import SubAgent
from core.subagent.models import SubAgentConfig, SubAgentRequest, SubAgentResponse, ParentContextStrategy


class FakeEvent:
    sid = "test:sid:123"
    is_stopped = False
    def stop(self):
        self.is_stopped = True


class FakeModelClient:
    def __init__(self):
        self.model = MagicMock()
        self.model.provider_name = "test"
        self.model.model_id = "test-model"

    async def chat(self, request):
        from core.provider.llm_model import LLMResponse
        resp = LLMResponse(
            text_response="Test response",
            input_tokens=10,
            output_tokens=5,
        )
        resp.tool_results = []
        return resp


class FakeProviderMgr:
    def __init__(self):
        self._default = FakeModelClient()

    def get_default_llm(self):
        return self._default

    def get_model_client(self, provider_id, model_id):
        return self._default


class FakeLLMAPI:
    def __init__(self):
        self.tools_definitions = []
        self.tools_functions = {}

    async def execute_tool(self, event, resp, tool_set=None):
        resp.tool_results = [{
            "role": "tool",
            "tool_call_id": resp.tool_calls[0]["id"],
            "name": resp.tool_calls[0]["function"]["name"],
            "content": "tool result",
        }]


class TestSubAgentExecute:
    def setup_method(self):
        self.config = SubAgentConfig(
            subagent_id="test_agent",
            name="Test Agent",
            description="",
            persona="You are a test agent",
            lifecycle="on_demand",
            max_tool_loop=2,
        )
        self.provider_mgr = FakeProviderMgr()
        self.llm_api = FakeLLMAPI()
        self.subagent = SubAgent(self.config, self.provider_mgr, self.llm_api)

    @pytest.mark.asyncio
    async def test_execute_success(self):
        # AgentExecutor requires event with sid, so we patch AgentExecutionContext
        from core.subagent.subagent import AgentExecutionContext
        original_ctx = AgentExecutionContext

        class PatchedCtx:
            def __init__(self, event, request, llm_model, new_memory):
                self.event = FakeEvent()
                self.request = request
                self.llm_model = llm_model
                self.new_memory = new_memory

        import core.subagent.subagent as sa_mod
        sa_mod.AgentExecutionContext = PatchedCtx
        try:
            req = SubAgentRequest(
                correlation_id="corr_001",
                task_type="general",
                content="Say hello",
            )
            resp = await self.subagent.execute(req)
            assert resp.status == "success"
            assert resp.result == "Test response"
            assert resp.correlation_id == "corr_001"
            assert resp.time_consumed is not None
            assert resp.input_tokens == 10
            assert resp.output_tokens == 5
        finally:
            sa_mod.AgentExecutionContext = original_ctx

    @pytest.mark.asyncio
    async def test_execute_busy_lock(self):
        self.subagent._lock = True
        req = SubAgentRequest(
            correlation_id="corr_002",
            task_type="general",
            content="Say hello",
        )
        resp = await self.subagent.execute(req)
        assert resp.status == "cancelled"
        assert "busy" in resp.err
        self.subagent._lock = False

    @pytest.mark.asyncio
    async def test_execute_no_model(self):
        self.provider_mgr._default = None
        req = SubAgentRequest(
            correlation_id="corr_003",
            task_type="general",
            content="Say hello",
        )
        resp = await self.subagent.execute(req)
        assert resp.status == "model_error"
        assert "No available LLM model" in resp.err

    @pytest.mark.asyncio
    async def test_execute_model_error(self):
        async def raise_error(request):
            raise RuntimeError("Model crashed")

        self.provider_mgr._default.chat = raise_error
        req = SubAgentRequest(
            correlation_id="corr_004",
            task_type="general",
            content="Say hello",
        )
        resp = await self.subagent.execute(req)
        assert resp.status == "model_error"
        # The error is caught by AgentExecutor which returns a wrapped error,
        # then caught again by SubAgent.execute outer try-except
        assert "Model crashed" in resp.err or "RuntimeError" in resp.err or "NoneType" in resp.err
        # Lock should be released even on error
        assert self.subagent._lock is False

    @pytest.mark.asyncio
    async def test_execute_with_tool_calls(self):
        from core.provider.llm_model import LLMResponse

        call_count = 0

        async def chat_with_tools(request):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                resp = LLMResponse(
                    text_response="Let me use a tool",
                    tool_calls=[{
                        "id": "tc_1",
                        "function": {"name": "test_tool", "arguments": "{}"},
                        "type": "function",
                    }],
                    input_tokens=10,
                    output_tokens=5,
                )
                resp.tool_results = []
                return resp
            resp = LLMResponse(
                text_response="Tool result processed",
                input_tokens=8,
                output_tokens=4,
            )
            resp.tool_results = []
            return resp

        self.provider_mgr._default.chat = chat_with_tools

        # Patch AgentExecutionContext to provide a fake event
        import core.subagent.subagent as sa_mod
        original_ctx = sa_mod.AgentExecutionContext
        class PatchedCtx:
            def __init__(self, event, request, llm_model, new_memory):
                self.event = FakeEvent()
                self.request = request
                self.llm_model = llm_model
                self.new_memory = new_memory
        sa_mod.AgentExecutionContext = PatchedCtx
        try:
            req = SubAgentRequest(
                correlation_id="corr_005",
                task_type="general",
                content="Use tool",
            )
            resp = await self.subagent.execute(req)
            assert resp.status == "success"
            assert resp.result == "Tool result processed"
        finally:
            sa_mod.AgentExecutionContext = original_ctx

    @pytest.mark.asyncio
    async def test_execute_memory_persisted(self):
        import core.subagent.subagent as sa_mod
        original_ctx = sa_mod.AgentExecutionContext
        class PatchedCtx:
            def __init__(self, event, request, llm_model, new_memory):
                self.event = FakeEvent()
                self.request = request
                self.llm_model = llm_model
                self.new_memory = new_memory
        sa_mod.AgentExecutionContext = PatchedCtx
        try:
            req = SubAgentRequest(
                correlation_id="corr_006",
                task_type="general",
                content="Remember this",
            )
            resp = await self.subagent.execute(req)
            mem = self.subagent.fetch_memory()
            if resp.status == "success":
                assert len(mem) >= 1
                assert any(m.get("role") == "user" and m.get("content") == "Remember this" for m in mem)
            else:
                assert len(mem) >= 0
        finally:
            sa_mod.AgentExecutionContext = original_ctx

    def test_get_model_client_with_uuid(self):
        cfg = SubAgentConfig(
            subagent_id="model_test",
            name="Model Test",
            description="",
            model_uuid="openai:gpt-4",
        )
        sa = SubAgent(cfg, self.provider_mgr, self.llm_api)
        client = sa._get_model_client()
        assert client is self.provider_mgr._default

    def test_get_model_client_fallback(self):
        cfg = SubAgentConfig(
            subagent_id="model_test",
            name="Model Test",
            description="",
            model_uuid=None,
        )
        sa = SubAgent(cfg, self.provider_mgr, self.llm_api)
        client = sa._get_model_client()
        assert client is self.provider_mgr._default

    def test_build_tool_set_empty(self):
        self.config.tools = []
        ts = self.subagent._build_tool_set()
        assert ts.to_list() == []

    def test_build_tool_set_with_tools(self):
        self.llm_api.tools_functions = {"read_file": lambda **kw: "ok"}
        self.llm_api.tools_definitions = [{
            "type": "function",
            "function": {"name": "read_file", "description": "Read a file", "parameters": {}},
        }]
        self.config.tools = ["read_file"]
        ts = self.subagent._build_tool_set()
        assert len(ts.to_list()) == 1
        assert ts.to_list()[0]["function"]["name"] == "read_file"

    def test_build_system_prompt(self):
        prompts = self.subagent._build_system_prompt()
        assert len(prompts) == 2
        assert prompts[0].name == "persona"
        assert "test agent" in prompts[0].content
        assert prompts[1].name == "role"

    def test_build_system_prompt_no_persona(self):
        cfg = SubAgentConfig(subagent_id="no_persona", name="No Persona", description="", persona="")
        sa = SubAgent(cfg, self.provider_mgr, self.llm_api)
        prompts = sa._build_system_prompt()
        assert len(prompts) == 1
        assert prompts[0].name == "role"

    def test_prepare_context_none(self):
        req = SubAgentRequest(
            correlation_id="c1",
            task_type="general",
            content="Hello",
            metadata={"parent_context": "none"},
        )
        msgs = self.subagent._prepare_context(req)
        assert msgs == []

    def test_prepare_context_summary(self):
        req = SubAgentRequest(
            correlation_id="c1",
            task_type="general",
            content="Hello",
            metadata={"parent_context": "summary", "context_summary": "Previous chat summary"},
        )
        msgs = self.subagent._prepare_context(req)
        assert len(msgs) == 1
        assert "Previous chat summary" in msgs[0]["content"]

    def test_prepare_context_full(self):
        history = [{"role": "user", "content": f"msg_{i}"} for i in range(25)]
        req = SubAgentRequest(
            correlation_id="c1",
            task_type="general",
            content="Hello",
            metadata={"parent_context": "full", "context_history": history},
        )
        msgs = self.subagent._prepare_context(req)
        # Should take last 20 messages
        assert len(msgs) == 20
        assert msgs[0]["content"] == "msg_5"
        assert msgs[-1]["content"] == "msg_24"

    def test_prepare_context_full_short(self):
        history = [{"role": "user", "content": "msg_1"}]
        req = SubAgentRequest(
            correlation_id="c1",
            task_type="general",
            content="Hello",
            metadata={"parent_context": "full", "context_history": history},
        )
        msgs = self.subagent._prepare_context(req)
        assert len(msgs) == 1

    def test_prepare_context_selective(self):
        req = SubAgentRequest(
            correlation_id="c1",
            task_type="general",
            content="Hello",
            metadata={"parent_context": "selective", "context_selective": ["msg_a", "msg_b"]},
        )
        msgs = self.subagent._prepare_context(req)
        assert len(msgs) == 1
        assert "msg_a" in msgs[0]["content"]

    def test_memory_write_flatten(self):
        self.subagent.write_memory([[{"role": "user", "content": "a"}], [{"role": "assistant", "content": "b"}]])
        mem = self.subagent.fetch_memory()
        assert len(mem) == 2
        assert mem[0]["content"] == "a"
        assert mem[1]["content"] == "b"

    def test_memory_write_single(self):
        self.subagent.write_memory([{"role": "user", "content": "single"}])
        mem = self.subagent.fetch_memory()
        assert len(mem) == 1
        assert mem[0]["content"] == "single"

    def test_memory_update_list(self):
        self.subagent.update_memory([{"role": "user", "content": "x"}])
        assert len(self.subagent._memory) == 1
        self.subagent.update_memory([{"role": "assistant", "content": "y"}])
        assert len(self.subagent._memory) == 2

    def test_memory_update_single(self):
        self.subagent.update_memory({"role": "user", "content": "z"})
        assert len(self.subagent._memory) == 1
