import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.agent.base_agent_executor import BaseAgentExecutionContext
from core.plugin import PluginManager, registry
from core.plugin.plugin_context import PluginContext
from core.provider import EmbeddingModelClient, LLMModelClient, ModelType


@pytest.fixture(autouse=True)
def isolated_plugin_components(monkeypatch):
    monkeypatch.setattr(registry, "_plugin_components", {})


@pytest.mark.anyio
async def test_register_subagent_is_plugin_owned_and_updates_settings_while_preserving_scopes(tmp_path):
    from core.agent.subagent_presets import SubAgentPreset as StoredSubAgentPreset
    from core.agent.subagent_presets import ReadOnlyPresetError, SubAgentPresetStore
    from core.plugin import SubAgentPreset

    store = SubAgentPresetStore(tmp_path / "presets.json")
    context = object.__new__(PluginContext)
    context.plugin_mgr = Mock(wraps=PluginManager(ctx=context))
    context.plugin_mgr.get_plugin_id_for_module.return_value = "research_plugin"
    context.subagent_mgr = SimpleNamespace(presets=store)
    defaults = SubAgentPreset(name="Research", instruction_source="custom", instruction="Study")

    item = await context.register_subagent(defaults)
    context.plugin_mgr.get_plugin_id_for_module.assert_called_with(__name__)
    assert store.get_enabled_by_name("Research", session_id="session")[0] == item["id"]
    assert "Research" in store.build_presets_prompt("session").content
    assert item["plugin_id"] == "research_plugin"
    with pytest.raises(ReadOnlyPresetError):
        await store.save(StoredSubAgentPreset(name="Renamed", enabled=False), item["id"])
    with pytest.raises(ReadOnlyPresetError):
        await store.delete(item["id"])
    await store.replace_scopes({item["id"]: {"allow": ["session"]}})

    restored = SubAgentPresetStore(store.path)
    await restored.initialize()
    context.subagent_mgr.presets = restored
    assert restored.list() == []
    defaults.description = "Updated by plugin"
    defaults.enabled = False
    registered = await asyncio.gather(*(context.register_subagent(defaults) for _ in range(3)))
    assert all(result == restored.list()[0] for result in registered)
    assert registered[0]["id"] == item["id"]
    assert registered[0]["name"] == "Research"
    assert registered[0]["description"] == "Updated by plugin"
    assert registered[0]["enabled"] is False
    assert restored.get_scopes() == {item["id"]: {"allow": ["session"]}}

    with pytest.raises(ReadOnlyPresetError):
        await restored.delete(item["id"])


@pytest.mark.anyio
async def test_register_subagent_rejects_conflicts_and_invalid_defaults(tmp_path):
    from core.agent.subagent_presets import DuplicatePresetNameError
    from core.agent.subagent_presets import SubAgentPreset as StoredSubAgentPreset
    from core.agent.subagent_presets import SubAgentPresetStore
    from core.plugin import SubAgentPreset
    from pydantic import ValidationError

    store = SubAgentPresetStore(tmp_path / "presets.json")
    context = object.__new__(PluginContext)
    context.plugin_mgr = Mock(wraps=PluginManager(ctx=context))
    context.plugin_mgr.get_plugin_id_for_module.return_value = "first"
    context.subagent_mgr = SimpleNamespace(presets=store)
    item = await context.register_subagent(SubAgentPreset(name="Research"))
    context.plugin_mgr.get_plugin_id_for_module.return_value = "second"
    with pytest.raises(DuplicatePresetNameError):
        await context.register_subagent(SubAgentPreset(name="Research"))
    await store.save(StoredSubAgentPreset(name="User preset"))
    with pytest.raises(DuplicatePresetNameError):
        await context.register_subagent(SubAgentPreset(name="User preset"))
    with pytest.raises(ValidationError):
        await context.register_subagent(SubAgentPreset(name="Invalid", max_steps=0))
    assert store.get(item["id"]).name == "Research"
    assert len(store.list()) == 2


@pytest.mark.anyio
async def test_register_subagent_only_accepts_plugin_descriptor():
    from core.agent.subagent_presets import SubAgentPreset as StoredSubAgentPreset
    from core.plugin import SubAgentPreset
    from pydantic import BaseModel

    assert not issubclass(SubAgentPreset, BaseModel)
    context = object.__new__(PluginContext)
    for invalid in ({"name": "Research"}, StoredSubAgentPreset(name="Research"), None):
        with pytest.raises(TypeError, match="core.plugin.SubAgentPreset"):
            await context.register_subagent(invalid)


@pytest.mark.anyio
async def test_register_subagent_converts_plugin_fields_without_sharing_lists(tmp_path):
    from dataclasses import asdict

    from core.agent.subagent_presets import SubAgentPresetStore
    from core.plugin import SubAgentPreset

    context = object.__new__(PluginContext)
    context.plugin_mgr = Mock(wraps=PluginManager(ctx=context))
    context.plugin_mgr.get_plugin_id_for_module.return_value = "plugin"
    store = SubAgentPresetStore(tmp_path / "presets.json")
    context.subagent_mgr = SimpleNamespace(presets=store)
    preset = SubAgentPreset(
        name="Research", description="Study tasks", instruction_source="mixed",
        persona_id="persona", instruction="Research thoroughly", max_steps=10,
        tool_mode="custom", tools=["search"], exclude_tools_from_main=True,
        skills=["review"], enabled=False, model="provider:model",
    )
    item = await context.register_subagent(preset)
    assert store.get(item["id"]).model_dump() == asdict(preset)
    preset.tools.append("mutated")
    preset.skills.append("mutated")
    assert store.get(item["id"]).tools == ["search"]
    assert store.get(item["id"]).skills == ["review"]
    first, second = SubAgentPreset(name="First"), SubAgentPreset(name="Second")
    first.tools.append("search")
    first.skills.append("review")
    assert second.tools == second.skills == []


@pytest.mark.anyio
async def test_register_subagent_binds_tool_instances_without_copying_or_serializing_them(tmp_path):
    from core.agent.subagent_presets import SubAgentPresetStore
    from core.plugin import SubAgentPreset
    from core.utils.tool_utils import BaseTool

    class PrivateTool(BaseTool):
        name = "private_tool"

        def __deepcopy__(self, memo):
            raise AssertionError("Runtime tools must not be copied")

        async def execute(self, event):
            return "private result"

    store = SubAgentPresetStore(tmp_path / "presets.json")
    context = object.__new__(PluginContext)
    context.plugin_mgr = Mock(wraps=PluginManager(ctx=context))
    context.plugin_mgr.get_plugin_id_for_module.return_value = "plugin"
    context.subagent_mgr = SimpleNamespace(presets=store)
    tool = PrivateTool(ctx=context)
    preset = SubAgentPreset(name="Private", tool_mode="custom", tools=["search", tool])
    item = await context.register_subagent(preset)
    assert item["tools"] == ["search", "private_tool"]
    assert store.get_plugin_tools(item["id"]) == [tool]
    restored = SubAgentPresetStore(store.path)
    await restored.initialize()
    assert restored.list() == []
    assert restored.get_plugin_tools(item["id"]) == []

    with pytest.raises(ValueError, match="Duplicate plugin subagent tool"):
        await context.register_subagent(SubAgentPreset(name="Private", tools=[tool, tool]))
    with pytest.raises(TypeError, match="BaseTool instances"):
        await context.register_subagent(SubAgentPreset(name="Invalid", tools=[PrivateTool]))
    assert store.get_plugin_tools(item["id"]) == [tool]


@pytest.mark.anyio
async def test_register_subagent_requires_plugin_and_manager():
    from core.plugin import SubAgentPreset

    context = object.__new__(PluginContext)
    context.plugin_mgr = None
    with pytest.raises(RuntimeError, match="not associated"):
        await context.register_subagent(SubAgentPreset(name="Research"))
    context.plugin_mgr = Mock(wraps=PluginManager(ctx=context))
    context.plugin_mgr.get_plugin_id_for_module.return_value = "plugin"
    context.subagent_mgr = None
    with pytest.raises(RuntimeError, match="manager is not available"):
        await context.register_subagent(SubAgentPreset(name="Research"))


@pytest.fixture
def agent_factory_context():
    context = object.__new__(PluginContext)
    context.provider_mgr = Mock()
    return context


@pytest.mark.anyio
async def test_unregister_subagent_removes_owned_preset_tools_and_scopes(tmp_path):
    from core.agent.subagent_presets import SubAgentPresetStore
    from core.plugin import SubAgentPreset
    from core.utils.tool_utils import BaseTool

    store = SubAgentPresetStore(tmp_path / "presets.json")
    context = object.__new__(PluginContext)
    context.plugin_mgr = Mock(wraps=PluginManager(ctx=context))
    context.plugin_mgr.get_plugin_id_for_module.return_value = "plugin"
    context.subagent_mgr = SimpleNamespace(presets=store)
    tool = Mock(spec=BaseTool)
    tool.name = "private"
    item = await context.register_subagent(SubAgentPreset(name="Private", tools=[tool]))
    other = await context.register_subagent(SubAgentPreset(name="Other"))
    await store.replace_scopes({item["id"]: {"allow": ["session"]}, other["id"]: {"deny": ["session"]}})

    async def unregister():
        return await context.unregister_subagent(item["id"])

    results = await asyncio.gather(*(unregister() for _ in range(3)))

    assert results.count(True) == 1
    assert results.count(False) == 2
    context.plugin_mgr.get_plugin_id_for_module.assert_called_with(__name__)
    assert store.list() == [other]
    assert store.get_scopes() == {other["id"]: {"deny": ["session"]}}
    assert store.get_plugin_tools(item["id"]) == []
    assert "Private" not in store.build_presets_prompt("other-session").content
    restored = SubAgentPresetStore(store.path)
    await restored.initialize()
    assert restored.list() == []
    assert restored.get_scopes() == {}
    assert (await context.register_subagent(SubAgentPreset(name="Private", tools=[tool])))["id"] == item["id"]


@pytest.mark.anyio
async def test_unregister_subagent_rejects_other_owners_and_keeps_state_on_write_failure(tmp_path, monkeypatch):
    from core.agent.subagent_presets import SubAgentPreset as StoredSubAgentPreset
    from core.agent.subagent_presets import SubAgentPresetStore
    from core.plugin import SubAgentPreset
    from core.utils.tool_utils import BaseTool

    store = SubAgentPresetStore(tmp_path / "presets.json")
    context = object.__new__(PluginContext)
    context.plugin_mgr = Mock(wraps=PluginManager(ctx=context))
    context.plugin_mgr.get_plugin_id_for_module.return_value = "owner"
    context.subagent_mgr = SimpleNamespace(presets=store)
    tool = Mock(spec=BaseTool)
    tool.name = "private"
    owned = await context.register_subagent(SubAgentPreset(name="Owned", tools=[tool]))
    user = await store.save(StoredSubAgentPreset(name="User"))
    await store.replace_scopes({owned["id"]: {"allow": ["session"]}})
    snapshot = store.path.read_bytes()
    context.plugin_mgr.get_plugin_id_for_module.return_value = "other"
    for identity in (owned["id"], user["id"]):
        with pytest.raises(PermissionError, match="not owned"):
            await context.unregister_subagent(identity)
    assert store.path.read_bytes() == snapshot

    context.plugin_mgr.get_plugin_id_for_module.return_value = "owner"

    def fail(*args):
        raise OSError("disk failure")

    monkeypatch.setattr("core.agent.subagent_presets.os.replace", fail)
    with pytest.raises(OSError, match="disk failure"):
        await context.unregister_subagent(owned["id"])
    assert store.list() == [user, owned]
    assert store.get_plugin_tools(owned["id"]) == [tool]
    assert store.get_scopes() == {owned["id"]: {"allow": ["session"]}}
    assert store.path.read_bytes() == snapshot


@pytest.mark.anyio
async def test_unregister_subagent_requires_valid_id_plugin_and_manager():
    context = object.__new__(PluginContext)
    for identity in (None, "", " ", 123):
        with pytest.raises(ValueError, match="non-empty string"):
            await context.unregister_subagent(identity)
    context.plugin_mgr = None
    with pytest.raises(RuntimeError, match="not associated"):
        await context.unregister_subagent("preset")
    context.plugin_mgr = Mock(wraps=PluginManager(ctx=context))
    context.plugin_mgr.get_plugin_id_for_module.return_value = "plugin"
    context.subagent_mgr = None
    with pytest.raises(RuntimeError, match="manager is not available"):
        await context.unregister_subagent("preset")


@pytest.mark.parametrize("explicit_none", [False, True])
def test_agent_factory_uses_default_llm_when_model_group_is_omitted(agent_factory_context, explicit_none):
    client = Mock(spec=LLMModelClient)
    agent_factory_context.provider_mgr.get_default_llm.return_value = client
    context = BaseAgentExecutionContext()
    kwargs = {"model_group": None} if explicit_none else {}

    executor = agent_factory_context.create_agent_executor(context=context, **kwargs)

    assert executor.model_group == [client]
    assert executor.context is context
    agent_factory_context.provider_mgr.get_default_llm.assert_called_once_with(session=None)


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
