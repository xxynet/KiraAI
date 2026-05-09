import json
import os
import tempfile
from pathlib import Path

import pytest

from core.subagent.registry import SubAgentRegistry
from core.subagent.models import SubAgentConfig


class TestSubAgentRegistry:
    def test_register_and_get(self):
        registry = SubAgentRegistry()
        cfg = SubAgentConfig(
            subagent_id="test_agent",
            name="Test Agent",
            description="A test agent",
        )
        assert registry.register(cfg) is True
        assert registry.get_config("test_agent") == cfg

    def test_register_without_id(self):
        registry = SubAgentRegistry()
        cfg = SubAgentConfig(
            subagent_id="",
            name="Test Agent",
            description="A test agent",
        )
        assert registry.register(cfg) is False

    def test_unregister(self):
        registry = SubAgentRegistry()
        cfg = SubAgentConfig(
            subagent_id="test_agent",
            name="Test Agent",
            description="A test agent",
        )
        registry.register(cfg)
        assert registry.unregister("test_agent") is True
        assert registry.get_config("test_agent") is None
        assert registry.unregister("nonexistent") is False

    def test_list_configs(self):
        registry = SubAgentRegistry()
        cfg1 = SubAgentConfig(subagent_id="agent1", name="Agent 1", description="")
        cfg2 = SubAgentConfig(subagent_id="agent2", name="Agent 2", description="")
        registry.register(cfg1)
        registry.register(cfg2)
        configs = registry.list_configs()
        assert len(configs) == 2
        assert "agent1" in configs
        assert "agent2" in configs

    def test_instance_cache(self):
        registry = SubAgentRegistry()
        registry.set_instance("agent1", {"fake": "instance"})
        assert registry.get_instance("agent1") == {"fake": "instance"}
        registry.remove_instance("agent1")
        assert registry.get_instance("agent1") is None

    def test_persistence(self, tmp_path, monkeypatch):
        from core.subagent import registry as reg_mod
        config_path = tmp_path / "subagents.json"
        monkeypatch.setattr(reg_mod, "SUBAGENT_CONFIG_PATH", config_path)

        registry = SubAgentRegistry()
        cfg = SubAgentConfig(
            subagent_id="persist_agent",
            name="Persist Agent",
            description="Should be saved",
            persona="Test persona",
            tools=["tool1"],
            lifecycle="app_scope",
        )
        registry.register(cfg)

        # Create a new registry instance to verify loading
        registry2 = SubAgentRegistry()
        loaded = registry2.get_config("persist_agent")
        assert loaded is not None
        assert loaded.name == "Persist Agent"
        assert loaded.persona == "Test persona"
        assert loaded.tools == ["tool1"]
        assert loaded.lifecycle == "app_scope"
