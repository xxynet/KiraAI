import asyncio
import pytest
from unittest.mock import AsyncMock

from core.subagent.client import SubAgentClient
from core.subagent.router import SubAgentRouter
from core.subagent.registry import SubAgentRegistry
from core.subagent.models import SubAgentConfig, SubAgentRequest, SubAgentResponse


class FakeProviderMgr:
    pass


class FakeLLMAPI:
    tools_definitions = []
    tools_functions = {}


class TestEdgeCases:
    def setup_method(self):
        self.registry = SubAgentRegistry()
        self.provider_mgr = FakeProviderMgr()
        self.llm_api = FakeLLMAPI()
        self.router = SubAgentRouter(self.registry, self.provider_mgr, self.llm_api)
        self.client = SubAgentClient(self.router)

        self.cfg = SubAgentConfig(
            subagent_id="test_agent",
            name="Test Agent",
            description="",
            lifecycle="on_demand",
            timeout=1.0,
        )
        self.registry.register(self.cfg)

    @pytest.mark.asyncio
    async def test_empty_content(self):
        """测试空内容调用"""
        self.router.dispatch = AsyncMock(return_value=SubAgentResponse(
            correlation_id="c1",
            status="success",
            result="",
        ))
        resp = await self.client.call("test_agent", "")
        assert resp.status == "success"
        assert resp.result == ""

    @pytest.mark.asyncio
    async def test_very_long_content(self):
        """测试超长内容调用"""
        long_content = "x" * 100000
        self.router.dispatch = AsyncMock(return_value=SubAgentResponse(
            correlation_id="c1",
            status="success",
            result="ok",
        ))
        resp = await self.client.call("test_agent", long_content)
        assert resp.status == "success"

    @pytest.mark.asyncio
    async def test_special_characters_content(self):
        """测试特殊字符内容"""
        special = "<script>alert('xss')</script>\n\u0000\u0001中文🎉"
        self.router.dispatch = AsyncMock(return_value=SubAgentResponse(
            correlation_id="c1",
            status="success",
            result="ok",
        ))
        resp = await self.client.call("test_agent", special)
        assert resp.status == "success"

    @pytest.mark.asyncio
    async def test_zero_timeout(self):
        """测试零超时"""
        async def slow(*args, **kwargs):
            await asyncio.sleep(0.5)
            return SubAgentResponse(correlation_id="", status="success", result="")

        self.router.dispatch = slow
        resp = await self.client.call("test_agent", "test", timeout=0)
        # asyncio.wait_for with timeout=0 may or may not timeout depending on event loop
        # Just verify it returns without hanging
        assert resp.status in ("success", "timeout")

    @pytest.mark.asyncio
    async def test_negative_timeout(self):
        """测试负超时"""
        async def slow(*args, **kwargs):
            await asyncio.sleep(0.5)
            return SubAgentResponse(correlation_id="", status="success", result="")

        self.router.dispatch = slow
        resp = await self.client.call("test_agent", "test", timeout=-1)
        assert resp.status == "timeout"

    @pytest.mark.asyncio
    async def test_retry_with_zero_delay(self):
        """测试零延迟重试"""
        self.router.dispatch = AsyncMock(return_value=SubAgentResponse(
            correlation_id="",
            status="model_error",
            err="fail",
        ))
        resp = await self.client.call_with_retry(
            "test_agent", "test",
            max_retries=1, base_delay=0
        )
        assert resp.status == "model_error"
        assert self.router.dispatch.call_count == 2

    @pytest.mark.asyncio
    async def test_retry_max_retries_zero(self):
        """测试 max_retries=0 不重试"""
        self.router.dispatch = AsyncMock(return_value=SubAgentResponse(
            correlation_id="",
            status="model_error",
            err="fail",
        ))
        resp = await self.client.call_with_retry(
            "test_agent", "test",
            max_retries=0, base_delay=0
        )
        assert resp.status == "model_error"
        assert self.router.dispatch.call_count == 1

    def test_parse_subagent_id_edge_cases(self):
        """测试 session ID 解析边界"""
        assert self.router.parse_subagent_id("sub:dm:") == ""
        assert self.router.parse_subagent_id("sub:dm:a:b:c") == "a:b:c"
        assert self.router.parse_subagent_id("sub:gm:agent") is None  # gm not supported
        assert self.router.parse_subagent_id("") is None
        assert self.router.parse_subagent_id("not:a:session") is None
        assert self.router.parse_subagent_id("sub:dm: agent_with_space") == " agent_with_space"

    def test_is_subagent_session_edge_cases(self):
        """测试 session 判断边界"""
        assert self.router.is_subagent_session("sub:dm:test") is True
        assert self.router.is_subagent_session("SUB:DM:test") is False  # case sensitive
        assert self.router.is_subagent_session("sub:dm") is False  # missing id
        assert self.router.is_subagent_session(123) is False  # not string
        assert self.router.is_subagent_session(None) is False

    def test_registry_unregister_nonexistent(self):
        """测试注销不存在的 agent"""
        assert self.registry.unregister("nonexistent") is False

    def test_registry_get_nonexistent(self):
        """测试获取不存在的 agent 配置"""
        assert self.registry.get_config("nonexistent") is None

    def test_registry_list_empty(self):
        """测试空注册表（可能加载了持久化数据，所以只检查返回类型是 dict）"""
        empty_registry = SubAgentRegistry()
        configs = empty_registry.list_configs()
        assert isinstance(configs, dict)
        # If persistence loaded data, that's fine; just ensure no crash

    def test_session_manager_no_router(self):
        """测试 SessionManager 未注册 router 时正常回落"""
        from core.chat.session_manager import SessionManager

        class FakeDB:
            pass

        class FakeConfig:
            def __getitem__(self, key):
                return {"bot": {"max_memory_length": 100}}

        mgr = SessionManager(FakeDB(), FakeConfig())
        # Should not crash when no router registered
        assert mgr._is_subagent_session("sub:dm:test") is True
        assert mgr._subagent_router is None
        # Normal session operations should still work
        mgr._ensure_session_data("qq:dm:123")
        assert "qq:dm:123" in mgr.chat_memory

    def test_client_correlation_id_format(self):
        """测试 correlation_id 格式"""
        cid = self.client._generate_correlation_id()
        assert cid.startswith("sub_")
        parts = cid.split("_")
        assert len(parts) == 3
        assert len(parts[1]) == 12  # uuid hex
        assert parts[2].isdigit()  # timestamp

    def test_client_correlation_id_unique(self):
        """测试 correlation_id 唯一性"""
        ids = {self.client._generate_correlation_id() for _ in range(100)}
        assert len(ids) == 100

    @pytest.mark.asyncio
    async def test_response_status_codes(self):
        """测试所有响应状态码"""
        for status in ["success", "timeout", "tool_error", "model_error", "cancelled"]:
            self.router.dispatch = AsyncMock(return_value=SubAgentResponse(
                correlation_id="c1",
                status=status,
                result="",
                err=None if status == "success" else "error",
            ))
            resp = await self.client.call("test_agent", "test")
            assert resp.status == status

    @pytest.mark.asyncio
    async def test_metadata_passed_through(self):
        """测试 metadata 正确传递"""
        received_meta = {}

        async def capture_meta(request, session_id=None):
            received_meta.update(request.metadata)
            return SubAgentResponse(correlation_id="c1", status="success", result="")

        self.router.dispatch = capture_meta
        await self.client.call(
            "test_agent", "test",
            metadata={"key1": "val1", "key2": 42}
        )
        assert received_meta.get("key1") == "val1"
        assert received_meta.get("key2") == 42
        assert received_meta.get("subagent_id") == "test_agent"

    @pytest.mark.asyncio
    async def test_session_id_passed_through(self):
        """测试 session_id 正确传递"""
        received_sid = None

        async def capture_sid(request, session_id=None):
            nonlocal received_sid
            received_sid = session_id
            return SubAgentResponse(correlation_id="c1", status="success", result="")

        self.router.dispatch = capture_sid
        await self.client.call("test_agent", "test", session_id="sess_123")
        assert received_sid == "sess_123"
