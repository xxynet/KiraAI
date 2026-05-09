import sys
from pathlib import Path

# Ensure project root is on path before any imports
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from core.subagent.models import (
    SubAgentConfig,
    SubAgentRequest,
    SubAgentResponse,
    ParentContextStrategy,
)


class TestSubAgentConfig:
    def test_default_values(self):
        cfg = SubAgentConfig(
            subagent_id="test_agent",
            name="Test Agent",
            description="A test agent",
        )
        assert cfg.subagent_id == "test_agent"
        assert cfg.name == "Test Agent"
        assert cfg.description == "A test agent"
        assert cfg.persona == ""
        assert cfg.model_uuid is None
        assert cfg.tools == []
        assert cfg.max_steps == 3
        assert cfg.timeout == 60.0
        assert cfg.context_strategy == ParentContextStrategy.NONE
        assert cfg.lifecycle == "on_demand"
        assert cfg.max_tool_loop == 2
        assert cfg.extra == {}

    def test_custom_values(self):
        cfg = SubAgentConfig(
            subagent_id="code_expert",
            name="Code Expert",
            description="Expert in coding",
            persona="You are a senior developer",
            model_uuid="openai:gpt-4",
            tools=["read_file", "write_file"],
            max_steps=5,
            timeout=120.0,
            context_strategy=ParentContextStrategy.SUMMARY,
            lifecycle="app_scope",
            max_tool_loop=4,
            extra={"key": "value"},
        )
        assert cfg.max_steps == 5
        assert cfg.timeout == 120.0
        assert cfg.context_strategy == ParentContextStrategy.SUMMARY
        assert cfg.lifecycle == "app_scope"
        assert cfg.extra == {"key": "value"}


class TestSubAgentRequest:
    def test_default_strategy(self):
        req = SubAgentRequest(
            correlation_id="abc123",
            task_type="general",
            content="Hello",
        )
        assert req.parent_context_strategy == ParentContextStrategy.NONE
        assert req.max_tokens is None
        assert req.allowed_tools is None

    def test_summary_strategy(self):
        req = SubAgentRequest(
            correlation_id="abc123",
            task_type="code_review",
            content="Review this code",
            metadata={"parent_context": "summary", "max_tokens": 2000},
        )
        assert req.parent_context_strategy == ParentContextStrategy.SUMMARY
        assert req.max_tokens == 2000

    def test_invalid_strategy_fallback(self):
        req = SubAgentRequest(
            correlation_id="abc123",
            task_type="general",
            content="Hello",
            metadata={"parent_context": "invalid_strategy"},
        )
        assert req.parent_context_strategy == ParentContextStrategy.NONE


class TestSubAgentResponse:
    def test_success_response(self):
        resp = SubAgentResponse(
            correlation_id="abc123",
            status="success",
            result="Done",
            metadata={"time_consumed": 1.5, "input_tokens": 100, "output_tokens": 50},
        )
        assert resp.status == "success"
        assert resp.result == "Done"
        assert resp.time_consumed == 1.5
        assert resp.input_tokens == 100
        assert resp.output_tokens == 50
        assert resp.err is None

    def test_error_response(self):
        resp = SubAgentResponse(
            correlation_id="abc123",
            status="timeout",
            err="Timed out after 60s",
        )
        assert resp.status == "timeout"
        assert resp.err == "Timed out after 60s"
        assert resp.result == ""
        assert resp.time_consumed is None
