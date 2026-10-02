import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.config import config_loader
from core.config.config_loader import KiraConfig
from core.provider import (
    BaseProvider, EmbeddingModelClient, ImageModelClient, LLMModelClient,
    ModelType, ProviderAPIError, ProviderManager, RerankModelClient,
    STTModelClient, TTSModelClient, VideoModelClient,
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
    response = api.patch('/api/providers/provider/status', json={'status': 'active'})
    assert response.status_code == 200
    assert response.json()['status'] == 'active'
    assert response.json()['name'] == 'Renamed'
    assert response.json()['config'] == {'option': 'value'}
    assert 'extra' in api.get('/api/providers/provider/models').json()['llm']
    assert manager.get_model_client('provider', 'extra', 'llm') is not None


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
@pytest.mark.parametrize('failure_stage', ['open', 'mkdir'])
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

    def fail_open(*args, **kwargs):
        raise PermissionError('Simulated configuration write failure')

    if failure_stage == 'open':
        monkeypatch.setattr(config_loader, 'open', fail_open, raising=False)
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

    if failure_stage == 'open':
        monkeypatch.delattr(config_loader, 'open')
    else:
        monkeypatch.setattr(config_loader.os, 'makedirs', original_makedirs)
    assert config_loader.CONFIG_PATH == tmp_path / 'config.json'
    response = api.patch('/api/providers/provider/status', json={'status': requested_status})
    assert response.status_code == 200
    assert response.json()['status'] == requested_status
    stored = json.loads(config_loader.CONFIG_PATH.read_text(encoding='utf-8'))
    assert stored['providers']['provider']['status'] == requested_status
