import pytest

from core.subagent.builtin.code_expert import CODE_EXPERT_CONFIG
from core.subagent.models import ParentContextStrategy


class TestBuiltinCodeExpert:
    def test_config_exists(self):
        assert CODE_EXPERT_CONFIG is not None

    def test_subagent_id(self):
        assert CODE_EXPERT_CONFIG.subagent_id == "code_expert"

    def test_name(self):
        assert CODE_EXPERT_CONFIG.name == "代码专家"

    def test_description(self):
        assert "代码" in CODE_EXPERT_CONFIG.description

    def test_persona_content(self):
        assert "软件工程师" in CODE_EXPERT_CONFIG.persona
        assert "代码审查" in CODE_EXPERT_CONFIG.persona

    def test_tools(self):
        assert "read_file" in CODE_EXPERT_CONFIG.tools
        assert "write_file" in CODE_EXPERT_CONFIG.tools

    def test_max_steps(self):
        assert CODE_EXPERT_CONFIG.max_steps == 5

    def test_timeout(self):
        assert CODE_EXPERT_CONFIG.timeout == 120.0

    def test_context_strategy(self):
        assert CODE_EXPERT_CONFIG.context_strategy == ParentContextStrategy.SUMMARY

    def test_lifecycle(self):
        assert CODE_EXPERT_CONFIG.lifecycle == "on_demand"

    def test_max_tool_loop(self):
        assert CODE_EXPERT_CONFIG.max_tool_loop == 4

    def test_config_is_valid(self):
        """验证配置能通过 SubAgentRegistry 注册"""
        from core.subagent.registry import SubAgentRegistry
        registry = SubAgentRegistry()
        result = registry.register(CODE_EXPERT_CONFIG)
        assert result is True
        loaded = registry.get_config("code_expert")
        assert loaded is not None
        assert loaded.name == "代码专家"
