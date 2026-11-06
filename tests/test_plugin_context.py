import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.agent.base_agent_executor import BaseAgentExecutionContext
from core.plugin.plugin_context import PluginContext
from core.provider import EmbeddingModelClient, LLMModelClient, ModelType


@pytest.fixture
def agent_factory_context():
    context = object.__new__(PluginContext)
    context.provider_mgr = Mock()
    return context


@pytest.mark.parametrize("explicit_none", [False, True])
def test_agent_factory_uses_default_llm_when_model_group_is_omitted(agent_factory_context, explicit_none):
    client = Mock(spec=LLMModelClient)
    agent_factory_context.provider_mgr.get_default_llm.return_value = client
    context = BaseAgentExecutionContext()
    kwargs = {"model_group": None} if explicit_none else {}

    executor = agent_factory_context.create_agent_executor(context=context, **kwargs)

    assert executor.model_group == [client]
    assert executor.context is context
    agent_factory_context.provider_mgr.get_default_llm.assert_called_once_with()


@pytest.mark.parametrize("empty_group", [False, True])
def test_agent_factory_preserves_explicit_model_group(agent_factory_context, empty_group):
    models = [] if empty_group else [Mock(spec=LLMModelClient), Mock(spec=LLMModelClient)]

    executor = agent_factory_context.create_agent_executor(models, context=BaseAgentExecutionContext())

    assert executor.model_group == models
    assert executor.model_group is not models
    agent_factory_context.provider_mgr.get_default_llm.assert_not_called()


def test_agent_factory_reports_missing_default_llm(agent_factory_context):
    agent_factory_context.provider_mgr.get_default_llm.return_value = None

    with pytest.raises(ValueError, match="No default LLM is available"):
        agent_factory_context.create_agent_executor(context=BaseAgentExecutionContext())


@pytest.mark.parametrize(
    ("method_name", "model_type", "client_type"),
    [
        ("get_llm_client", ModelType.LLM, LLMModelClient),
        ("get_embedding_client", ModelType.EMBEDDING, EmbeddingModelClient),
    ],
)
def test_model_lookup_returns_client_and_preserves_model_id(method_name, model_type, client_type):
    client = Mock(spec=client_type)
    manager = Mock()
    manager.get_model_client.return_value = client
    context = SimpleNamespace(provider_mgr=manager)

    assert getattr(PluginContext, method_name)(context, "provider:model:version") is client
    manager.get_model_client.assert_called_once_with("provider", "model:version", model_type)


@pytest.mark.parametrize("method_name", ["get_llm_client", "get_embedding_client"])
@pytest.mark.parametrize("error_type", [ValueError, RuntimeError])
def test_model_lookup_returns_none_on_ordinary_failure(method_name, error_type):
    manager = Mock()
    manager.get_model_client.side_effect = error_type("lookup failed")
    context = SimpleNamespace(provider_mgr=manager)

    assert getattr(PluginContext, method_name)(context, "provider:model") is None
    manager.get_model_client.assert_called_once()


@pytest.mark.parametrize("method_name", ["get_llm_client", "get_embedding_client"])
@pytest.mark.parametrize("error_type", [KeyboardInterrupt, SystemExit, asyncio.CancelledError])
def test_model_lookup_propagates_control_exceptions(method_name, error_type):
    manager = Mock()
    manager.get_model_client.side_effect = error_type("lookup interrupted")
    context = SimpleNamespace(provider_mgr=manager)

    with pytest.raises(error_type):
        getattr(PluginContext, method_name)(context, "provider:model")
    manager.get_model_client.assert_called_once()
