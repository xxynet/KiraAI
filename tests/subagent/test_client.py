import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock

from core.subagent.client import SubAgentClient
from core.subagent.router import SubAgentRouter
from core.subagent.registry import SubAgentRegistry
from core.subagent.models import SubAgentConfig, SubAgentRequest, SubAgentResponse


class FakeProviderMgr:
    pass


class FakeLLMAPI:
    tools_definitions = []
    tools_functions = {}


class TestSubAgentClient:
    def setup_method(self):
        self.registry = SubAgentRegistry()
        self.provider_mgr = FakeProviderMgr()
        self.llm_api = FakeLLMAPI()
        self.router = SubAgentRouter(self.registry, self.provider_mgr, self.llm_api)
        self.client = SubAgentClient(self.router)

        self.cfg = SubAgentConfig(
            subagent_id="test_agent",
            name="Test Agent",
            description="A test agent",
            lifecycle="on_demand",
            timeout=1.0,
        )
        self.registry.register(self.cfg)

    @pytest.mark.asyncio
    async def test_call_success(self):
        # Mock router.dispatch to return success
        self.router.dispatch = AsyncMock(return_value=SubAgentResponse(
            correlation_id="sub_abc_123",
            status="success",
            result="Done",
        ))

        resp = await self.client.call("test_agent", "Hello")
        assert resp.status == "success"
        assert resp.result == "Done"
        assert resp.correlation_id.startswith("sub_")

    @pytest.mark.asyncio
    async def test_call_not_found(self):
        resp = await self.client.call("nonexistent", "Hello")
        assert resp.status == "cancelled"
        assert "not found" in resp.err

    @pytest.mark.asyncio
    async def test_call_timeout(self):
        async def slow_dispatch(*args, **kwargs):
            await asyncio.sleep(5)
            return SubAgentResponse(correlation_id="", status="success", result="")

        self.router.dispatch = slow_dispatch
        resp = await self.client.call("test_agent", "Hello", timeout=0.1)
        assert resp.status == "timeout"
        assert "timed out" in resp.err

    @pytest.mark.asyncio
    async def test_call_nested_not_allowed(self):
        self.client._call_depth = 1
        resp = await self.client.call("test_agent", "Hello")
        assert resp.status == "cancelled"
        assert "Nested" in resp.err

    @pytest.mark.asyncio
    async def test_call_with_retry_success_on_first(self):
        self.router.dispatch = AsyncMock(return_value=SubAgentResponse(
            correlation_id="sub_abc_123",
            status="success",
            result="Done",
        ))
        resp = await self.client.call_with_retry("test_agent", "Hello", max_retries=2)
        assert resp.status == "success"
        assert self.router.dispatch.call_count == 1

    @pytest.mark.asyncio
    async def test_call_with_retry_success_on_second(self):
        call_count = 0

        async def fail_then_succeed(req, session_id=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return SubAgentResponse(correlation_id="", status="model_error", err="fail")
            return SubAgentResponse(correlation_id="", status="success", result="Done")

        self.router.dispatch = fail_then_succeed
        resp = await self.client.call_with_retry("test_agent", "Hello", max_retries=2, base_delay=0.01)
        assert resp.status == "success"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_call_with_retry_exhausted(self):
        self.router.dispatch = AsyncMock(return_value=SubAgentResponse(
            correlation_id="",
            status="model_error",
            err="fail",
        ))
        resp = await self.client.call_with_retry("test_agent", "Hello", max_retries=1, base_delay=0.01)
        assert resp.status == "model_error"
        assert self.router.dispatch.call_count == 2  # initial + 1 retry

    @pytest.mark.asyncio
    async def test_call_with_retry_cancelled_no_retry(self):
        self.router.dispatch = AsyncMock(return_value=SubAgentResponse(
            correlation_id="",
            status="cancelled",
            err="cancelled",
        ))
        resp = await self.client.call_with_retry("test_agent", "Hello", max_retries=2)
        assert resp.status == "cancelled"
        assert self.router.dispatch.call_count == 1  # no retry for cancelled
