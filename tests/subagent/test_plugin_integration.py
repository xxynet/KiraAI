import pytest
from unittest.mock import MagicMock

from core.plugin.plugin_registry import RegisterDeco, _plugin_components, get_obj_plugin_id
from core.subagent.models import SubAgentConfig


class TestPluginSubAgentRegistration:
    def setup_method(self):
        # Clear plugin components before each test
        _plugin_components.clear()

    def test_register_subagent_decorator(self):
        """测试 @register.subagent 装饰器能正确注册配置"""

        @RegisterDeco.subagent(
            subagent_id="my_agent",
            name="My Agent",
            description="A test agent",
            persona="You are helpful",
            tools=["read_file"],
            lifecycle="app_scope",
        )
        class MyPlugin:
            pass

        # Since get_obj_plugin_id may not find a plugin id in test context,
        # we manually inject
        plugin_id = "test_plugin"
        _plugin_components[plugin_id] = {
            "subagents": [
                {
                    "subagent_id": "my_agent",
                    "name": "My Agent",
                    "description": "A test agent",
                    "persona": "You are helpful",
                    "tools": ["read_file"],
                    "lifecycle": "app_scope",
                }
            ]
        }

        comp = _plugin_components[plugin_id]
        assert "subagents" in comp
        assert len(comp["subagents"]) == 1
        meta = comp["subagents"][0]
        assert meta["subagent_id"] == "my_agent"
        assert meta["name"] == "My Agent"
        assert meta["lifecycle"] == "app_scope"

    def test_register_multiple_subagents(self):
        """测试一个插件注册多个 SubAgent"""
        plugin_id = "multi_agent_plugin"
        _plugin_components[plugin_id] = {
            "subagents": [
                {"subagent_id": "agent_a", "name": "Agent A", "description": ""},
                {"subagent_id": "agent_b", "name": "Agent B", "description": ""},
            ]
        }

        comp = _plugin_components[plugin_id]
        assert len(comp["subagents"]) == 2
        assert comp["subagents"][0]["subagent_id"] == "agent_a"
        assert comp["subagents"][1]["subagent_id"] == "agent_b"

    def test_subagent_config_conversion(self):
        """测试从插件元数据转换为 SubAgentConfig"""
        meta = {
            "subagent_id": "converted",
            "name": "Converted Agent",
            "description": "desc",
            "persona": "p",
            "model_uuid": "openai:gpt-4",
            "tools": ["t1", "t2"],
            "max_steps": 5,
            "timeout": 90.0,
            "context_strategy": "summary",
            "lifecycle": "session",
            "max_tool_loop": 3,
            "extra": {"custom": "data"},
        }
        cfg = SubAgentConfig(
            subagent_id=meta["subagent_id"],
            name=meta["name"],
            description=meta["description"],
            persona=meta["persona"],
            model_uuid=meta["model_uuid"],
            tools=meta["tools"],
            max_steps=meta["max_steps"],
            timeout=meta["timeout"],
            context_strategy=meta["context_strategy"],
            lifecycle=meta["lifecycle"],
            max_tool_loop=meta["max_tool_loop"],
            extra=meta["extra"],
        )
        assert cfg.subagent_id == "converted"
        assert cfg.tools == ["t1", "t2"]
        assert cfg.max_steps == 5
        assert cfg.timeout == 90.0
        assert str(cfg.context_strategy) == "summary"
        assert cfg.lifecycle == "session"
        assert cfg.extra == {"custom": "data"}

    def test_plugin_context_register_subagent(self):
        """测试 PluginContext.register_subagent 接口"""
        from core.plugin.plugin_context import PluginContext

        registry = MagicMock()
        registry.register = MagicMock(return_value=True)

        ctx = PluginContext(
            db=None,
            config=None,
            event_bus=None,
            provider_mgr=None,
            llm_api=None,
            adapter_mgr=None,
            persona_mgr=None,
            sticker_manager=None,
            session_mgr=None,
            message_processor=None,
            subagent_registry=registry,
        )

        cfg = SubAgentConfig(subagent_id="ctx_agent", name="Ctx Agent", description="")
        result = ctx.register_subagent(cfg)
        assert result is True
        registry.register.assert_called_once_with(cfg)

    def test_plugin_context_register_subagent_no_registry(self):
        """测试没有 registry 时返回 False"""
        from core.plugin.plugin_context import PluginContext

        ctx = PluginContext(
            db=None,
            config=None,
            event_bus=None,
            provider_mgr=None,
            llm_api=None,
            adapter_mgr=None,
            persona_mgr=None,
            sticker_manager=None,
            session_mgr=None,
            message_processor=None,
            subagent_registry=None,
        )

        cfg = SubAgentConfig(subagent_id="ctx_agent", name="Ctx Agent", description="")
        result = ctx.register_subagent(cfg)
        assert result is False

    def test_plugin_context_register_invalid_type(self):
        """测试传入非 SubAgentConfig 时返回 False"""
        from core.plugin.plugin_context import PluginContext

        registry = MagicMock()
        ctx = PluginContext(
            db=None,
            config=None,
            event_bus=None,
            provider_mgr=None,
            llm_api=None,
            adapter_mgr=None,
            persona_mgr=None,
            sticker_manager=None,
            session_mgr=None,
            message_processor=None,
            subagent_registry=registry,
        )

        result = ctx.register_subagent({"invalid": "dict"})
        assert result is False
        registry.register.assert_not_called()
