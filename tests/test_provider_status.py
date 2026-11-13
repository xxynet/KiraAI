import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from core.chat.session_manager import SessionManager
from core.config import config_loader
from core.config.config_loader import KiraConfig
from core.provider import (
    BaseProvider,
    DecisionModelClient,
    EmbeddingModelClient,
    ImageModelClient,
    LLMModelClient,
    ModelType,
    ProviderAPIError,
    ProviderManager,
    RerankModelClient,
    STTModelClient,
    TTSModelClient,
    VideoModelClient,
)
from webui.routes.auth import require_auth
from webui.routes.providers import ProvidersRoutes


async def record_call(self, *args, **kwargs):
    self.calls = getattr(self, 'calls', 0) + 1
    return 'result'


async def record_stream(self, *args, **kwargs):
    self.calls = getattr(self, 'calls', 0) + 1
    yield 'chunk'


CAPABILITIES = [
    (ModelType.LLM, LLMModelClient, 'chat'),
    (ModelType.TTS, TTSModelClient, 'text_to_speech'),
    (ModelType.STT, STTModelClient, 'speech_to_text'),
    (ModelType.IMAGE, ImageModelClient, 'text_to_image'),
    (ModelType.IMAGE, ImageModelClient, 'image_to_image'),
    (ModelType.VIDEO, VideoModelClient, 'generate_video'),
    (ModelType.EMBEDDING, EmbeddingModelClient, 'embed'),
    (ModelType.RERANK, RerankModelClient, 'rerank'),
    (ModelType.DECISION, DecisionModelClient, 'noul'),
    (ModelType.DECISION, DecisionModelClient, 'choice'),
    (ModelType.DECISION, DecisionModelClient, 'score'),
]


class StubProvider(BaseProvider):
    models = {}
    constructions = 0
    remote_calls = 0

    def __init__(self, *args):
        super().__init__(*args)
        type(self).constructions += 1

    async def get_llm_list(self):
        type(self).remote_calls += 1
        return [{'id': 'model'}]


for model_type, base, method_name in CAPABILITIES:
    if model_type not in StubProvider.models:
        methods = {
            name: record_call for kind, _, name in CAPABILITIES if kind is model_type
        }
        if model_type is ModelType.LLM:
            methods['chat_stream'] = record_stream
        StubProvider.models[model_type] = type(f'Stub{base.__name__}', (base,), methods)


@pytest.fixture
def manager(monkeypatch, tmp_path):
    monkeypatch.setattr(config_loader, 'CONFIG_PATH', tmp_path / 'config.json')
    monkeypatch.setattr(ProviderManager, '_registry', {'stub': StubProvider})
    monkeypatch.setattr(ProviderManager, '_schemas', {'stub': {'provider_config': []}})
    monkeypatch.setattr(ProviderManager, '_manifests', {})
    monkeypatch.setattr(ProviderManager, '_manifest_dirs', {})
    monkeypatch.setattr(StubProvider, 'constructions', 0)
    monkeypatch.setattr(StubProvider, 'remote_calls', 0)
    instance = object.__new__(ProviderManager)
    instance._providers = {}
    instance.kira_config = KiraConfig({'providers': {}, 'models': {}})
    instance.kira_config['providers']['provider'] = {
        'format': 'stub', 'name': 'Test Provider', 'provider_config': {},
        'model_config': {kind.value: {'model': {}} for kind in ModelType},
    }
    instance.providers_config = instance.kira_config['providers']
    instance._load_providers()
    return instance


@pytest.fixture
def api(manager):
    app = FastAPI()
    app.dependency_overrides[require_auth] = lambda: 'test'
    routes = ProvidersRoutes(app, SimpleNamespace(
        kira_config=manager.kira_config, provider_manager=manager,
    ))
    routes.register()
    with TestClient(app) as client:
        yield client


def disable(manager):
    config = manager.kira_config['providers']['provider']
    config['status'] = 'inactive'
    manager.set_provider('provider', config)


def test_legacy_provider_enabled_and_disabled_provider_not_loaded_on_restart(manager):
    assert manager.get_provider('provider') is not None
    disable(manager)
    assert manager.get_provider('provider') is None
    assert manager.get_all_providers() == {}
    manager.kira_config.save_config()
    manager.kira_config = KiraConfig({'providers': {}, 'models': {}})
    manager.providers_config = manager.kira_config['providers']
    manager._load_providers()
    assert StubProvider.constructions == 1
    assert manager.get_provider('provider') is None


@pytest.mark.parametrize('kind,base,method_name', CAPABILITIES)
@pytest.mark.anyio
async def test_disabled_provider_blocks_new_and_retained_clients(manager, kind, base, method_name):
    client = manager.get_model_client('provider', 'model', kind)
    assert isinstance(client, base)
    method = getattr(client, method_name)
    assert await method() == 'result'
    pending = method()
    disable(manager)
    with pytest.raises(ProviderAPIError, match='disabled'):
        manager.get_model_client('provider', 'model', kind)
    with pytest.raises(ProviderAPIError, match='disabled'):
        await method()
    with pytest.raises(ProviderAPIError, match='disabled'):
        await pending
    assert client.calls == 1
    config = manager.kira_config['providers']['provider']
    config['status'] = 'active'
    manager.set_provider('provider', config)
    assert await method() == 'result'


@pytest.mark.anyio
async def test_disabled_provider_blocks_deferred_stream_and_remote_requests(manager):
    client = manager.get_model_client('provider', 'model', 'llm')
    assert [chunk async for chunk in client.chat_stream()] == ['chunk']
    stream = client.chat_stream()
    disable(manager)
    with pytest.raises(ProviderAPIError, match='disabled'):
        await anext(stream)
    with pytest.raises(ProviderAPIError, match='disabled'):
        await manager.fetch_remote_models('provider')
    result = await manager.health_check('provider', 'llm', 'model')
    assert result['success'] is False
    assert 'disabled' in result['error']
    assert client.calls == 1
    assert StubProvider.remote_calls == 0


@pytest.mark.parametrize('model_key', [
    'default_llm', 'default_fast_llm', 'default_vlm', 'default_tts', 'default_stt',
    'default_image', 'default_video', 'default_embedding', 'default_rerank',
])
def test_disabled_provider_blocks_default_models(manager, model_key):
    manager.kira_config['models'][model_key] = 'provider:model'
    disable(manager)
    with pytest.raises(ProviderAPIError, match='disabled'):
        getattr(manager, f'get_{model_key}')()


def test_status_api_persists_toggle_and_preserves_models_and_config(api, manager):
    assert api.get('/api/providers').json()[0]['status'] == 'active'
    response = api.patch('/api/providers/provider/status', json={'status': 'inactive'})
    assert response.status_code == 200
    assert response.json()['status'] == 'inactive'
    stored = json.loads(config_loader.CONFIG_PATH.read_text(encoding='utf-8'))
    assert stored['providers']['provider']['status'] == 'inactive'
    assert manager.get_provider('provider') is None
    response = api.put('/api/providers/provider', json={
        'name': 'Renamed', 'type': 'stub', 'config': {'option': 'value'},
    })
    assert response.status_code == 200
    assert response.json()['status'] == 'inactive'
    assert response.json()['config'] == {'option': 'value'}
    response = api.post('/api/providers/provider/models', json={
        'model_type': 'llm', 'model_id': 'extra',
    })
    assert response.status_code == 200
    assert manager.get_provider('provider') is None
    model_id = response.json()['model_id']
    response = api.patch('/api/providers/provider/status', json={'status': 'active'})
    assert response.status_code == 200
    assert response.json()['status'] == 'active'
    assert response.json()['name'] == 'Renamed'
    assert response.json()['config'] == {'option': 'value'}
    assert model_id in api.get('/api/providers/provider/models').json()['llm']
    assert manager.get_model_client('provider', model_id, 'llm') is not None


def test_provider_responses_include_configured_models(api, manager):
    providers = api.get('/api/providers')
    provider = api.get('/api/providers/provider')
    model_id = manager.get_model_info('provider', 'model', ModelType.LLM).model_id

    assert providers.status_code == provider.status_code == 200
    for item in (providers.json()[0], provider.json()):
        assert item['status'] == 'active'
        assert 'llm' in item['supported_model_types']
        assert item['model_config']['llm'][model_id]['model_name'] == 'model'


@pytest.mark.parametrize('status', ['active', 'inactive'])
def test_create_provider_honors_status(api, manager, status):
    response = api.post('/api/providers', json={'name': 'New', 'type': 'stub', 'status': status})
    assert response.status_code == 201
    provider = response.json()
    assert provider['status'] == status
    assert manager.kira_config['providers'][provider['id']]['status'] == status
    assert (manager.get_provider(provider['id']) is not None) == (status == 'active')


def test_update_provider_honors_explicit_status_and_api_validates_values(api, manager):
    response = api.put('/api/providers/provider', json={
        'name': 'Test Provider', 'type': 'stub', 'status': 'inactive',
    })
    assert response.status_code == 200
    assert response.json()['status'] == 'inactive'
    assert manager.get_provider('provider') is None
    assert api.patch('/api/providers/provider/status', json={'status': 'invalid'}).status_code == 422
    assert api.patch('/api/providers/missing/status', json={'status': 'active'}).status_code == 404


def test_failed_provider_initialization_is_reported_inactive(api, manager, monkeypatch):
    disable(manager)

    def fail_init(self, *args):
        raise ValueError('Invalid test configuration')

    monkeypatch.setattr(StubProvider, '__init__', fail_init)
    response = api.patch('/api/providers/provider/status', json={'status': 'active'})
    assert response.status_code == 200
    assert response.json()['status'] == 'inactive'
    assert manager.get_provider('provider') is None


def test_status_api_without_lifecycle():
    app = FastAPI()
    app.dependency_overrides[require_auth] = lambda: 'test'
    ProvidersRoutes(app, None).register()
    with TestClient(app) as client:
        created = client.post('/api/providers', json={'name': 'New', 'type': 'stub'}).json()
        url = f"/api/providers/{created['id']}"
        response = client.patch(f'{url}/status', json={'status': 'inactive'})
        assert response.status_code == 200
        assert response.json()['status'] == 'inactive'
        response = client.put(url, json={'name': 'Renamed', 'type': 'stub'})
        assert response.json()['status'] == 'inactive'
        assert client.patch('/api/providers/missing/status', json={'status': 'active'}).status_code == 404


@pytest.mark.parametrize('previous_status', [None, 'active', 'inactive'])
@pytest.mark.parametrize('failure_stage', ['replace', 'mkdir'])
def test_status_save_failure_rolls_back_without_resetting_provider(
    api, manager, monkeypatch, tmp_path, previous_status, failure_stage,
):
    config = manager.kira_config['providers']['provider']
    if previous_status is not None:
        config['status'] = previous_status
    manager.set_provider('provider', config)
    manager.kira_config.save_config()
    original_file = config_loader.CONFIG_PATH.read_bytes()
    original_provider = manager.get_provider('provider')
    constructions = StubProvider.constructions
    requested_status = 'active' if previous_status == 'inactive' else 'inactive'

    def fail_replace(*args, **kwargs):
        raise PermissionError('Simulated configuration write failure')

    original_replace = config_loader.os.replace
    if failure_stage == 'replace':
        monkeypatch.setattr(config_loader.os, 'replace', fail_replace)
    else:
        original_makedirs = config_loader.os.makedirs

        def fail_config_directory(path, *args, **kwargs):
            if str(path) == str(config_loader.CONFIG_PATH.parent):
                raise PermissionError('Simulated configuration directory failure')
            return original_makedirs(path, *args, **kwargs)

        monkeypatch.setattr(config_loader.os, 'makedirs', fail_config_directory)

    response = api.patch('/api/providers/provider/status', json={'status': requested_status})
    assert response.status_code == 500
    assert response.json()['detail'] == 'Failed to save provider status'
    assert config.get('status') == previous_status
    assert ('status' in config) == (previous_status is not None)
    assert manager.get_provider('provider') is original_provider
    assert StubProvider.constructions == constructions
    assert config_loader.CONFIG_PATH.read_bytes() == original_file
    expected_status = 'inactive' if previous_status == 'inactive' else 'active'
    assert api.get('/api/providers/provider').json()['status'] == expected_status

    if failure_stage == 'replace':
        monkeypatch.setattr(config_loader.os, 'replace', original_replace)
    else:
        monkeypatch.setattr(config_loader.os, 'makedirs', original_makedirs)
    assert config_loader.CONFIG_PATH == tmp_path / 'config.json'
    response = api.patch('/api/providers/provider/status', json={'status': requested_status})
    assert response.status_code == 200
    assert response.json()['status'] == requested_status
    stored = json.loads(config_loader.CONFIG_PATH.read_text(encoding='utf-8'))
    assert stored['providers']['provider']['status'] == requested_status


@pytest.mark.anyio
@pytest.mark.parametrize('kind', list(ModelType))
async def test_health_check_preserves_supported_capabilities(manager, kind):
    result = await manager.health_check('provider', kind.value, 'model')
    supported = kind not in {ModelType.STT, ModelType.IMAGE, ModelType.VIDEO}
    assert result['success'] is supported
    if supported:
        assert result['latency'] >= 0
        assert result['error'] is None
    else:
        assert result['latency'] is None
        assert result['error'] == f'Health check not supported for {kind.value} models'


@pytest.mark.anyio
async def test_health_check_delegates_to_provider_client_override(manager, monkeypatch):
    calls = []

    async def custom_probe(self):
        calls.append(self.model.model_name)
        raise ProviderAPIError('Custom probe failure')

    client_class = StubProvider.models[ModelType.IMAGE]
    monkeypatch.setattr(client_class, 'health_check', custom_probe)
    result = await manager.health_check('provider', 'image', 'model')
    assert calls == ['model']
    assert result == {
        'success': False, 'latency': None, 'error': 'Custom probe failure',
    }


def _session_api(manager, session_db):
    app = FastAPI()
    app.dependency_overrides[require_auth] = lambda: 'test'
    session_manager = SessionManager(session_db, manager.kira_config)
    ProvidersRoutes(app, SimpleNamespace(
        kira_config=manager.kira_config,
        provider_manager=manager,
        session_manager=session_manager,
    )).register()
    return app, session_manager


def _add_llm_model(manager, provider_id, model_id):
    # providers are already migrated to model_config_version 2 by _load_providers,
    # so new entries need the full versioned shape to pass validate_model_names.
    manager.kira_config['providers'][provider_id]['model_config']['llm'][model_id] = {
        'model_name': model_id, 'config': {}, 'legacy_ids': [model_id],
    }


async def _seed_llm_sessions(session_manager):
    await session_manager.update_session('bili:dm:gone', llm_model='provider:model')
    await session_manager.update_session('bili:dm:kept', llm_model='provider:keep')
    await session_manager.update_session('bili:dm:none', data={'note': 'untouched'})


async def _assert_session_cleanup(session_manager):
    gone = await session_manager.get_session('bili:dm:gone')
    assert gone.data.get('llm_model') is None
    assert (await session_manager.get_session('bili:dm:kept')).data['llm_model'] == 'provider:keep'
    assert (await session_manager.get_session('bili:dm:none')).data == {'note': 'untouched'}


@pytest.mark.anyio
async def test_delete_model_clears_dangling_session_llm_references(manager, session_db):
    _add_llm_model(manager, 'provider', 'keep')
    app, sessions = _session_api(manager, session_db)
    await _seed_llm_sessions(sessions)

    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        response = await client.delete('/api/providers/provider/models/llm/model')

    assert response.status_code == 200, response.text
    await _assert_session_cleanup(sessions)


@pytest.mark.anyio
async def test_sync_models_removal_clears_dangling_session_llm_references(manager, session_db):
    _add_llm_model(manager, 'provider', 'keep')
    app, sessions = _session_api(manager, session_db)
    await _seed_llm_sessions(sessions)

    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/api/providers/provider/models/sync/llm', json={
            'delete_ids': ['model'],
        })

    assert response.status_code == 200, response.text
    assert response.json()['removed'] == 1
    await _assert_session_cleanup(sessions)


@pytest.mark.anyio
async def test_delete_provider_clears_dangling_session_llm_references(manager, session_db):
    manager.kira_config['providers']['other'] = {
        'format': 'stub', 'name': 'Other', 'provider_config': {},
        'model_config': {'llm': {'m2': {}}},
    }
    app, sessions = _session_api(manager, session_db)
    await sessions.update_session('bili:dm:gone', llm_model='provider:model')
    await sessions.update_session('bili:dm:kept', llm_model='other:m2')

    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        response = await client.delete('/api/providers/provider')

    assert response.status_code == 204
    assert (await sessions.get_session('bili:dm:gone')).data.get('llm_model') is None
    assert (await sessions.get_session('bili:dm:kept')).data['llm_model'] == 'other:m2'


@pytest.mark.anyio
async def test_delete_provider_save_failure_returns_500_and_keeps_provider(
    manager, session_db, monkeypatch,
):
    app, sessions = _session_api(manager, session_db)
    await sessions.update_session('bili:dm:gone', llm_model='provider:model')

    def fail_replace(*args, **kwargs):
        raise PermissionError('Simulated configuration write failure')

    monkeypatch.setattr(config_loader.os, 'replace', fail_replace)

    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        response = await client.delete('/api/providers/provider')

    assert response.status_code == 500
    assert 'provider' in manager.kira_config['providers']
    assert 'provider' in manager._providers
    # cleanup must not run: the session keeps its now-dangling reference
    assert (await sessions.get_session('bili:dm:gone')).data['llm_model'] == 'provider:model'


@pytest.mark.anyio
async def test_delete_model_survives_session_cleanup_failure(manager):
    class FailingSessionManager:
        async def clear_llm_model_references(self, is_available):
            raise RuntimeError('cleanup boom')

    app = FastAPI()
    app.dependency_overrides[require_auth] = lambda: 'test'
    ProvidersRoutes(app, SimpleNamespace(
        kira_config=manager.kira_config,
        provider_manager=manager,
        session_manager=FailingSessionManager(),
    )).register()

    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        response = await client.delete('/api/providers/provider/models/llm/model')

    assert response.status_code == 200
    assert response.json() == {'success': True}
