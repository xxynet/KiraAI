import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.plugin.plugin_context import PluginContext
from core.provider import EmbeddingModelClient, LLMModelClient, ModelType


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
