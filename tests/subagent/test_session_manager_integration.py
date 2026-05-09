import pytest
from unittest.mock import MagicMock

from core.chat.session_manager import SessionManager
from core.subagent.router import SubAgentRouter
from core.subagent.registry import SubAgentRegistry
from core.subagent.models import SubAgentConfig


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


class FakeProviderMgr:
    pass


class FakeLLMAPI:
    tools_definitions = []
    tools_functions = {}


class TestSessionManagerSubAgentIntegration:
    def setup_method(self):
        self.db = FakeDB()
        self.config = FakeKiraConfig()
        self.session_mgr = SessionManager(self.db, self.config)

        self.registry = SubAgentRegistry()
        self.provider_mgr = FakeProviderMgr()
        self.llm_api = FakeLLMAPI()
        self.router = SubAgentRouter(self.registry, self.provider_mgr, self.llm_api)

        self.cfg = SubAgentConfig(
            subagent_id="test_agent",
            name="Test Agent",
            description="",
            lifecycle="app_scope",
        )
        self.registry.register(self.cfg)
        self.session_mgr.register_subagent_router(self.router)

    def test_register_router(self):
        assert self.session_mgr._subagent_router is self.router

    def test_is_subagent_session(self):
        assert self.session_mgr._is_subagent_session("sub:dm:test_agent") is True
        assert self.session_mgr._is_subagent_session("qq:dm:12345") is False

    def test_get_session_info_subagent(self):
        info = self.session_mgr.get_session_info("sub:dm:test_agent")
        assert info.adapter_name == "sub"
        assert info.session_type == "dm"
        assert info.session_id == "test_agent"

    def test_fetch_memory_routes_to_subagent(self):
        # Pre-populate subagent memory via router
        inst = self.router._get_or_create_instance(self.cfg)
        inst._memory = [{"role": "user", "content": "hello"}]

        mem = self.session_mgr.fetch_memory("sub:dm:test_agent")
        assert len(mem) == 1
        assert mem[0]["content"] == "hello"

    def test_read_memory_routes_to_subagent(self):
        inst = self.router._get_or_create_instance(self.cfg)
        inst._memory = [{"role": "assistant", "content": "hi"}]

        mem = self.session_mgr.read_memory("sub:dm:test_agent")
        assert len(mem) == 1
        assert mem[0]["content"] == "hi"

    def test_write_memory_routes_to_subagent(self):
        self.session_mgr.write_memory("sub:dm:test_agent", [[{"role": "user", "content": "test"}]])
        # write_memory routes to router.write_memory which writes to existing instance
        mem = self.session_mgr.read_memory("sub:dm:test_agent")
        assert len(mem) == 1
        assert mem[0]["content"] == "test"

    def test_update_memory_routes_to_subagent(self):
        self.session_mgr.update_memory("sub:dm:test_agent", [{"role": "user", "content": "new"}])
        mem = self.session_mgr.read_memory("sub:dm:test_agent")
        assert len(mem) == 1
        assert mem[0]["content"] == "new"

    def test_delete_session_routes_to_subagent(self):
        self.session_mgr.delete_session("sub:dm:test_agent")
        # Should not crash; app_scope instances are not removed by delete_session

    def test_get_memory_count_routes_to_subagent(self):
        inst = self.router._get_or_create_instance(self.cfg)
        inst._memory = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
        count = self.session_mgr.get_memory_count("sub:dm:test_agent")
        assert count == 2

    def test_normal_session_unchanged(self):
        # Normal sessions should still work
        self.session_mgr._ensure_session_data("qq:dm:12345")
        self.session_mgr.update_memory("qq:dm:12345", [{"role": "user", "content": "hello"}])
        mem = self.session_mgr.fetch_memory("qq:dm:12345")
        assert len(mem) >= 1
        assert mem[-1]["content"] == "hello"
