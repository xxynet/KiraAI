import pytest
from unittest.mock import MagicMock

from core.subagent.router import SubAgentRouter
from core.subagent.registry import SubAgentRegistry
from core.subagent.models import SubAgentConfig, SubAgentRequest, SubAgentResponse


class FakeProviderMgr:
    pass


class FakeLLMAPI:
    tools_definitions = []
    tools_functions = {}


class TestSubAgentRouter:
    def setup_method(self):
        self.registry = SubAgentRegistry()
        self.provider_mgr = FakeProviderMgr()
        self.llm_api = FakeLLMAPI()
        self.router = SubAgentRouter(self.registry, self.provider_mgr, self.llm_api)

        self.cfg = SubAgentConfig(
            subagent_id="test_agent",
            name="Test Agent",
            description="A test agent",
            lifecycle="on_demand",
        )
        self.registry.register(self.cfg)

    def test_is_subagent_session(self):
        assert self.router.is_subagent_session("sub:dm:test_agent") is True
        assert self.router.is_subagent_session("qq:dm:12345") is False
        assert self.router.is_subagent_session("") is False
        assert self.router.is_subagent_session(None) is False

    def test_parse_subagent_id(self):
        assert self.router.parse_subagent_id("sub:dm:test_agent") == "test_agent"
        assert self.router.parse_subagent_id("qq:dm:12345") is None
        assert self.router.parse_subagent_id("sub:dm:") == ""

    def test_get_or_create_on_demand(self):
        inst1 = self.router._get_or_create_instance(self.cfg)
        inst2 = self.router._get_or_create_instance(self.cfg)
        assert inst1 is not inst2  # on_demand creates new instance each time

    def test_get_or_create_app_scope(self):
        cfg_app = SubAgentConfig(
            subagent_id="app_agent",
            name="App Agent",
            description="",
            lifecycle="app_scope",
        )
        self.registry.register(cfg_app)
        inst1 = self.router._get_or_create_instance(cfg_app)
        inst2 = self.router._get_or_create_instance(cfg_app)
        assert inst1 is inst2  # app_scope caches instance

    def test_get_or_create_session_scope(self):
        cfg_session = SubAgentConfig(
            subagent_id="session_agent",
            name="Session Agent",
            description="",
            lifecycle="session",
        )
        self.registry.register(cfg_session)
        inst1 = self.router._get_or_create_instance(cfg_session, session_id="sess_1")
        inst2 = self.router._get_or_create_instance(cfg_session, session_id="sess_1")
        inst3 = self.router._get_or_create_instance(cfg_session, session_id="sess_2")
        assert inst1 is inst2
        assert inst1 is not inst3

    @pytest.mark.asyncio
    async def test_dispatch_missing_subagent_id(self):
        req = SubAgentRequest(
            correlation_id="abc",
            task_type="general",
            content="Hello",
            metadata={},
        )
        resp = await self.router.dispatch(req)
        assert resp.status == "cancelled"
        assert "Missing subagent_id" in resp.err

    @pytest.mark.asyncio
    async def test_dispatch_not_found(self):
        req = SubAgentRequest(
            correlation_id="abc",
            task_type="general",
            content="Hello",
            metadata={"subagent_id": "nonexistent"},
        )
        resp = await self.router.dispatch(req)
        assert resp.status == "cancelled"
        assert "not registered" in resp.err

    def test_memory_operations(self):
        # Test that memory operations don't crash for non-existent sessions
        assert self.router.fetch_memory("sub:dm:unknown") == []
        self.router.write_memory("sub:dm:unknown", [])
        self.router.update_memory("sub:dm:unknown", [])
        self.router.delete_session("sub:dm:unknown")

    def test_cleanup_session(self):
        cfg_session = SubAgentConfig(
            subagent_id="session_agent",
            name="Session Agent",
            description="",
            lifecycle="session",
        )
        self.registry.register(cfg_session)
        self.router._get_or_create_instance(cfg_session, session_id="sess_1")
        assert "sess_1" in self.router._session_instances
        self.router.cleanup_session("sess_1")
        assert "sess_1" not in self.router._session_instances
