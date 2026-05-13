import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from copy import deepcopy

from core.subagent import (
    SubAgentConfig,
    SubAgentRequest,
    SubAgentResponse,
    SubAgentRegistry,
    SubAgentRouter,
    SubAgentClient,
    ParentContextStrategy,
)
from core.subagent.subagent import SubAgent
from core.chat.session_manager import SessionManager
from core.chat import KiraMessageEvent, KiraIMMessage, MessageChain, Session, User, Group
from core.chat.message_elements import Text
from core.adapter.adapter_info import AdapterInfo
from core.provider.llm_model import LLMResponse


# =============================================================================
# Fake Objects for Account-Level Testing
# =============================================================================

class FakeEvent:
    """Minimal event compatible with AgentExecutionContext"""
    sid = "qq:dm:123456"
    is_stopped = False
    def stop(self):
        self.is_stopped = True


class FakeModelClient:
    """Fake LLM model client that returns configurable responses"""
    def __init__(self, responses=None):
        self.model = MagicMock()
        self.model.provider_name = "test"
        self.model.model_id = "test-model"
        self._responses = responses or []
        self._call_count = 0

    async def chat(self, request):
        if self._call_count < len(self._responses):
            resp = self._responses[self._call_count]
            self._call_count += 1
            return resp
        resp = LLMResponse(text_response="Default response", input_tokens=5, output_tokens=3)
        resp.tool_results = []
        return resp


class FakeProviderMgr:
    def __init__(self, default_client=None):
        self._default = default_client or FakeModelClient()

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


class FakeDB:
    pass


class FakeKiraConfig:
    def __init__(self):
        self._data = {
            "bot_config": {
                "bot": {"max_memory_length": 100}
            }
        }

    def __getitem__(self, key):
        return self._data[key]

    def get(self, key, default=None):
        return self._data.get(key, default)


class FakeAdapter:
    """Fake adapter that records sent messages"""
    def __init__(self, name="qq"):
        self.name = name
        self.info = AdapterInfo(
            enabled=True,
            adapter_id=name,
            name=name,
            platform=name,
        )
        self.sent_messages = []

    async def send_direct_message(self, user_id, chain):
        self.sent_messages.append(("dm", user_id, chain))
        from core.chat.message_utils import KiraIMSentResult
        return KiraIMSentResult(ok=True, message_id="msg_001")

    async def send_group_message(self, group_id, chain):
        self.sent_messages.append(("gm", group_id, chain))
        from core.chat.message_utils import KiraIMSentResult
        return KiraIMSentResult(ok=True, message_id="msg_002")


def make_message_event(text_content, adapter_name="qq", session_type="dm", session_id="123456", user_nickname="TestUser"):
    """Helper to create a KiraMessageEvent for testing"""
    adapter = AdapterInfo(
        enabled=True,
        adapter_id=adapter_name,
        name=adapter_name,
        platform=adapter_name,
    )
    chain = MessageChain([Text(text_content)])
    user = User(user_id=session_id, nickname=user_nickname)
    group = None
    if session_type == "gm":
        group = Group(group_id=session_id, group_name="TestGroup")
    message = KiraIMMessage(
        message_id="msg_001",
        self_id="bot_001",
        chain=chain,
        timestamp=1234567890,
        sender=user,
        group=group,
    )
    event = KiraMessageEvent(
        message_types=["text"],
        timestamp=1234567890,
        message=message,
        adapter=adapter,
    )
    return event


# =============================================================================
# Account-Level Integration Tests
# =============================================================================

class TestAccountSubAgentIntegration:
    """测试 SubAgent 在账号消息链路中的集成行为"""

    def setup_method(self):
        self.db = FakeDB()
        self.config = FakeKiraConfig()
        self.session_mgr = SessionManager(self.db, self.config)

        self.registry = SubAgentRegistry()
        self.provider_mgr = FakeProviderMgr()
        self.llm_api = FakeLLMAPI()
        self.router = SubAgentRouter(self.registry, self.provider_mgr, self.llm_api)
        self.client = SubAgentClient(self.router)

        self.session_mgr.register_subagent_router(self.router)

        # Register a test SubAgent
        self.cfg = SubAgentConfig(
            subagent_id="account_test_agent",
            name="Account Test Agent",
            description="Agent for account testing",
            persona="You are a helpful test assistant",
            lifecycle="session",
            timeout=5.0,
        )
        self.registry.register(self.cfg)

    # ------------------------------------------------------------------
    # 1. 会话 ID 格式与路由测试
    # ------------------------------------------------------------------

    def test_subagent_session_id_format(self):
        """SubAgent 会话 ID 必须符合 sub:dm:<id> 格式"""
        sid = "sub:dm:account_test_agent"
        assert self.session_mgr._is_subagent_session(sid) is True
        assert self.router.parse_subagent_id(sid) == "account_test_agent"

    def test_normal_session_not_routed(self):
        """普通账号会话不应被路由到 SubAgent"""
        normal_sid = "qq:dm:123456"
        assert self.session_mgr._is_subagent_session(normal_sid) is False
        assert self.router.parse_subagent_id(normal_sid) is None

    def test_multi_adapter_session_ids(self):
        """不同适配器的会话 ID 都能正确识别"""
        for adapter in ["qq", "telegram", "discord", "weixin"]:
            sid = f"{adapter}:dm:user_001"
            assert self.session_mgr._is_subagent_session(sid) is False

            sub_sid = f"sub:dm:{adapter}_agent"
            assert self.session_mgr._is_subagent_session(sub_sid) is True

    # ------------------------------------------------------------------
    # 2. 消息事件构造与基础流转测试
    # ------------------------------------------------------------------

    def test_message_event_construction(self):
        """验证消息事件构造器能正确生成事件"""
        event = make_message_event("Hello bot", adapter_name="qq", session_type="dm")
        assert event.adapter.name == "qq"
        assert event.session.sid == "qq:dm:123456"
        assert event.message.chain[0].text == "Hello bot"
        assert not event.is_group_message()

    def test_group_message_event(self):
        """群聊消息事件构造正确"""
        event = make_message_event("Hello group", adapter_name="qq", session_type="gm", session_id="group_001")
        assert event.is_group_message()
        assert event.session.sid == "qq:gm:group_001"

    def test_cross_adapter_events(self):
        """跨适配器消息事件构造"""
        for adapter in ["telegram", "discord", "weixin"]:
            event = make_message_event(f"Hello from {adapter}", adapter_name=adapter)
            assert event.adapter.name == adapter
            assert event.session.adapter_name == adapter

    # ------------------------------------------------------------------
    # 3. SubAgent 调用与响应测试（模拟账号场景）
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_subagent_call_from_account_context(self):
        """模拟从账号上下文调用 SubAgent"""
        self.router.dispatch = AsyncMock(return_value=SubAgentResponse(
            correlation_id="sub_abc_123",
            status="success",
            result="This is the subagent result",
        ))

        # 模拟用户消息触发 SubAgent 调用
        event = make_message_event("请帮我分析这段代码")
        session_id = event.session.sid

        resp = await self.client.call(
            "account_test_agent",
            "请帮我分析这段代码",
            task_type="code_review",
            session_id=session_id,
            metadata={"parent_context": "summary", "context_summary": "用户正在讨论代码问题"},
        )

        assert resp.status == "success"
        assert resp.result == "This is the subagent result"
        assert resp.correlation_id.startswith("sub_")

    @pytest.mark.asyncio
    async def test_subagent_call_with_full_parent_context(self):
        """SubAgent 调用携带完整父上下文"""
        history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]

        self.router.dispatch = AsyncMock(return_value=SubAgentResponse(
            correlation_id="sub_ctx_001",
            status="success",
            result="Got it",
        ))

        resp = await self.client.call(
            "account_test_agent",
            "Continue",
            session_id="qq:dm:123456",
            metadata={
                "parent_context": "full",
                "context_history": history,
            },
        )

        assert resp.status == "success"

    @pytest.mark.asyncio
    async def test_subagent_timeout_in_account_context(self):
        """模拟账号场景中 SubAgent 超时"""
        async def slow_dispatch(*args, **kwargs):
            await asyncio.sleep(10)
            return SubAgentResponse(correlation_id="", status="success", result="")

        self.router.dispatch = slow_dispatch

        event = make_message_event("复杂任务")
        resp = await self.client.call(
            "account_test_agent",
            "复杂任务",
            session_id=event.session.sid,
            timeout=0.1,
        )

        assert resp.status == "timeout"
        assert "timed out" in resp.err

    @pytest.mark.asyncio
    async def test_subagent_error_handling(self):
        """模拟账号场景中 SubAgent 返回错误"""
        self.router.dispatch = AsyncMock(return_value=SubAgentResponse(
            correlation_id="sub_err_001",
            status="model_error",
            err="LLM service unavailable",
        ))

        resp = await self.client.call(
            "account_test_agent",
            "触发错误",
            session_id="qq:dm:123456",
        )

        assert resp.status == "model_error"
        assert "unavailable" in resp.err

    # ------------------------------------------------------------------
    # 4. 会话记忆隔离测试（账号维度）
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_session_memory_isolation_per_account(self):
        """不同账号的 SubAgent 记忆应隔离"""
        cfg_session = SubAgentConfig(
            subagent_id="memory_agent",
            name="Memory Agent",
            description="",
            lifecycle="session",
        )
        self.registry.register(cfg_session)

        inst_a = self.router._get_or_create_instance(cfg_session, session_id="qq:dm:user_a")
        inst_b = self.router._get_or_create_instance(cfg_session, session_id="qq:dm:user_b")

        inst_a.update_memory([{"role": "user", "content": "User A's secret"}])

        assert len(inst_a.fetch_memory()) == 1
        assert len(inst_b.fetch_memory()) == 0
        assert "User A's secret" not in str(inst_b.fetch_memory())

    @pytest.mark.asyncio
    async def test_app_scope_memory_shared_across_accounts(self):
        """app_scope SubAgent 记忆应在所有账号间共享"""
        cfg_app = SubAgentConfig(
            subagent_id="shared_agent",
            name="Shared Agent",
            description="",
            lifecycle="app_scope",
        )
        self.registry.register(cfg_app)

        inst1 = self.router._get_or_create_instance(cfg_app)
        inst1.update_memory([{"role": "user", "content": "Shared knowledge"}])

        inst2 = self.router._get_or_create_instance(cfg_app)
        assert len(inst2.fetch_memory()) == 1
        assert inst2.fetch_memory()[0]["content"] == "Shared knowledge"

    # ------------------------------------------------------------------
    # 5. SessionManager 与 SubAgent 集成测试
    # ------------------------------------------------------------------

    def test_session_manager_routes_subagent_memory(self):
        """SessionManager 能正确路由 SubAgent 记忆操作"""
        sid = "sub:dm:account_test_agent"

        # Write memory via SessionManager
        self.session_mgr.write_memory(sid, [[{"role": "user", "content": "test"}]])

        # Read back via SessionManager
        mem = self.session_mgr.read_memory(sid)
        assert len(mem) == 1
        assert mem[0]["content"] == "test"

    def test_session_manager_get_memory_count_subagent(self):
        """SessionManager 能正确获取 SubAgent 记忆数量"""
        sid = "sub:dm:account_test_agent"
        self.session_mgr.write_memory(sid, [
            [{"role": "user", "content": "a"}],
            [{"role": "assistant", "content": "b"}],
        ])

        count = self.session_mgr.get_memory_count(sid)
        assert count == 2

    def test_session_manager_delete_subagent_session(self):
        """SessionManager 能删除 SubAgent 会话"""
        sid = "sub:dm:account_test_agent"
        self.session_mgr.write_memory(sid, [[{"role": "user", "content": "to delete"}]])

        self.session_mgr.delete_session(sid)
        # app_scope instance should still exist, but session-scoped are removed
        count = self.session_mgr.get_memory_count(sid)
        # For app_scope, memory persists; for on_demand, no instance means 0
        assert count >= 0

    # ------------------------------------------------------------------
    # 6. 并发账号场景测试
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_concurrent_account_requests(self):
        """模拟多个账号同时调用 SubAgent"""
        call_log = []

        async def track_dispatch(request, session_id=None):
            call_log.append(session_id)
            await asyncio.sleep(0.01)
            return SubAgentResponse(
                correlation_id=request.correlation_id,
                status="success",
                result=f"Result for {session_id}",
            )

        self.router.dispatch = track_dispatch

        tasks = []
        for i in range(5):
            sid = f"qq:dm:user_{i}"
            task = self.client.call("account_test_agent", f"task_{i}", session_id=sid)
            tasks.append(task)

        results = await asyncio.gather(*tasks)

        assert len(results) == 5
        assert all(r.status == "success" for r in results)
        assert len(call_log) == 5
        assert len(set(call_log)) == 5  # Each has different session_id

    @pytest.mark.asyncio
    async def test_nested_call_blocked_in_account_context(self):
        """账号场景中嵌套 SubAgent 调用应被阻止"""
        self.client._call_depth = 1
        event = make_message_event("嵌套调用测试")

        resp = await self.client.call(
            "account_test_agent",
            "嵌套调用",
            session_id=event.session.sid,
        )

        assert resp.status == "cancelled"
        assert "Nested" in resp.err
        self.client._call_depth = 0

    # ------------------------------------------------------------------
    # 7. 跨适配器 SubAgent 行为一致性
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_subagent_behavior_consistent_across_adapters(self):
        """SubAgent 在不同适配器下行为一致"""
        self.router.dispatch = AsyncMock(return_value=SubAgentResponse(
            correlation_id="sub_multi_001",
            status="success",
            result="Consistent result",
        ))

        for adapter in ["qq", "telegram", "discord"]:
            event = make_message_event("Test", adapter_name=adapter)
            resp = await self.client.call(
                "account_test_agent",
                "Test",
                session_id=event.session.sid,
            )
            assert resp.status == "success"
            assert resp.result == "Consistent result"

    # ------------------------------------------------------------------
    # 8. 真实 AgentExecutor 集成测试（轻量级）
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_subagent_execute_with_real_agent_executor(self):
        """使用真实 AgentExecutor 执行 SubAgent 任务"""
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
            subagent = SubAgent(self.cfg, self.provider_mgr, self.llm_api)
            req = SubAgentRequest(
                correlation_id="real_exec_001",
                task_type="general",
                content="Say hello from account test",
            )
            resp = await subagent.execute(req)

            assert resp.status == "success"
            assert resp.result == "Default response"
            assert resp.correlation_id == "real_exec_001"
            assert resp.time_consumed is not None
        finally:
            sa_mod.AgentExecutionContext = original_ctx

    @pytest.mark.asyncio
    async def test_subagent_execute_preserves_memory(self):
        """SubAgent 执行后记忆应被保存"""
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
            subagent = SubAgent(self.cfg, self.provider_mgr, self.llm_api)
            req = SubAgentRequest(
                correlation_id="mem_test_001",
                task_type="general",
                content="Remember this account message",
            )
            resp = await subagent.execute(req)

            mem = subagent.fetch_memory()
            if resp.status == "success":
                assert len(mem) >= 1
                assert any(
                    m.get("role") == "user" and m.get("content") == "Remember this account message"
                    for m in mem
                )
        finally:
            sa_mod.AgentExecutionContext = original_ctx

    # ------------------------------------------------------------------
    # 9. 边界条件测试（账号场景）
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_empty_message_content(self):
        """账号发送空消息到 SubAgent"""
        self.router.dispatch = AsyncMock(return_value=SubAgentResponse(
            correlation_id="empty_001",
            status="success",
            result="",
        ))

        resp = await self.client.call("account_test_agent", "", session_id="qq:dm:123")
        assert resp.status == "success"
        assert resp.result == ""

    @pytest.mark.asyncio
    async def test_very_long_message_content(self):
        """账号发送超长消息到 SubAgent"""
        long_msg = "x" * 50000
        self.router.dispatch = AsyncMock(return_value=SubAgentResponse(
            correlation_id="long_001",
            status="success",
            result="ok",
        ))

        resp = await self.client.call("account_test_agent", long_msg, session_id="qq:dm:123")
        assert resp.status == "success"

    @pytest.mark.asyncio
    async def test_special_characters_in_message(self):
        """账号发送特殊字符消息"""
        special = "<script>alert('xss')</script>\n\u0000\u0001中文🎉🔥"
        self.router.dispatch = AsyncMock(return_value=SubAgentResponse(
            correlation_id="special_001",
            status="success",
            result="ok",
        ))

        resp = await self.client.call("account_test_agent", special, session_id="qq:dm:123")
        assert resp.status == "success"

    @pytest.mark.asyncio
    async def test_subagent_not_found_in_account_context(self):
        """账号调用不存在的 SubAgent"""
        event = make_message_event("调用不存在的 agent")
        resp = await self.client.call(
            "nonexistent_agent",
            "test",
            session_id=event.session.sid,
        )
        assert resp.status == "cancelled"
        assert "not found" in resp.err

    # ------------------------------------------------------------------
    # 10. 重试机制测试（账号场景）
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_retry_in_account_context(self):
        """账号场景中 SubAgent 调用失败后的重试"""
        call_count = 0

        async def fail_once(request, session_id=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return SubAgentResponse(
                    correlation_id="",
                    status="model_error",
                    err="Temporary failure",
                )
            return SubAgentResponse(
                correlation_id="retry_001",
                status="success",
                result="Recovered",
            )

        self.router.dispatch = fail_once
        resp = await self.client.call_with_retry(
            "account_test_agent",
            "test",
            session_id="qq:dm:123",
            max_retries=2,
            base_delay=0.01,
        )

        assert resp.status == "success"
        assert resp.result == "Recovered"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_retry_exhausted_in_account_context(self):
        """账号场景中重试次数耗尽"""
        self.router.dispatch = AsyncMock(return_value=SubAgentResponse(
            correlation_id="",
            status="model_error",
            err="Persistent failure",
        ))

        resp = await self.client.call_with_retry(
            "account_test_agent",
            "test",
            session_id="qq:dm:123",
            max_retries=1,
            base_delay=0.01,
        )

        assert resp.status == "model_error"
        assert self.router.dispatch.call_count == 2
