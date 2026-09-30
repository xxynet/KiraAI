import json

import pytest

from core.plugin import store as store_module
from core.plugin.store import PluginStore, StoreSource


@pytest.fixture
def cached_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module.time, "time", lambda: 1000)
    data = {"meta": {"version": "original"}, "plugins": [], "categories": {"tools": {"name": "Tools"}}}
    (tmp_path / "catalog.json").write_text(json.dumps(data), encoding="utf-8")
    source = StoreSource(url="https://example.test/catalog", cache_file="catalog.json", updated_at=999)
    return PluginStore(source, cache_dir=tmp_path), data


@pytest.mark.asyncio
@pytest.mark.parametrize("force_refresh", [False, True])
async def test_fresh_cache_and_force_refresh_preserve_complete_catalog(cached_store, monkeypatch, force_refresh):
    store, cached = cached_store
    remote = {**cached, "meta": {"version": "remote"}}
    requests = []

    async def fetch(url, timeout):
        requests.append((url, timeout))
        return remote

    monkeypatch.setattr(store_module, "get_json", fetch)
    result = await store.fetch(
        force_refresh=force_refresh, persist_cache=True,
    )

    expected = remote if force_refresh else cached
    assert result.data == expected
    assert json.loads((store.cache_dir / "catalog.json").read_text(encoding="utf-8")) == expected
    assert list(store.cache_dir.iterdir()) == [store.cache_dir / "catalog.json"]
    if force_refresh:
        assert requests == [("https://example.test/catalog", 15.0)]
        assert result.cache_file == "catalog.json"
        assert result.updated_at == 1000
    else:
        assert not requests
        assert result.cache_file is None
        assert result.updated_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize("allow_fallback", [False, True])
async def test_remote_failure_preserves_distinct_browsing_and_update_policies(cached_store, monkeypatch, allow_fallback):
    store, cached = cached_store
    store = PluginStore(
        StoreSource(url="https://example.test/catalog", cache_file="catalog.json", updated_at=0),
        cache_dir=store.cache_dir,
    )
    failure = ConnectionError("source unavailable")
    original_bytes = (store.cache_dir / "catalog.json").read_bytes()

    async def fail_fetch(url, timeout):
        raise failure

    monkeypatch.setattr(store_module, "get_json", fail_fetch)
    if allow_fallback:
        result = await store.fetch(
            persist_cache=True, allow_cache_fallback=True,
        )
        assert result.data == cached
        assert result.fetch_error is failure
        assert result.cache_file is None
        assert result.updated_at is None
    else:
        with pytest.raises(ConnectionError) as captured:
            await store.fetch(persist_cache=True)
        assert captured.value is failure
    assert (store.cache_dir / "catalog.json").read_bytes() == original_bytes


@pytest.mark.asyncio
@pytest.mark.parametrize("strict", [False, True])
async def test_corrupt_fresh_cache_keeps_existing_entry_point_policy(cached_store, monkeypatch, strict):
    store, remote = cached_store
    (store.cache_dir / "catalog.json").write_text("invalid JSON", encoding="utf-8")
    requests = []

    async def fetch(url, timeout):
        requests.append(url)
        return remote

    monkeypatch.setattr(store_module, "get_json", fetch)
    if strict:
        with pytest.raises(json.JSONDecodeError):
            await store.fetch(strict_cache=True, persist_cache=True)
        assert not requests
    else:
        result = await store.fetch(persist_cache=True)
        assert result.data == remote
        assert requests == ["https://example.test/catalog"]
        assert json.loads((store.cache_dir / "catalog.json").read_text(encoding="utf-8")) == remote


@pytest.mark.asyncio
async def test_direct_url_fetch_does_not_create_source_cache(tmp_path, monkeypatch):
    store = PluginStore(StoreSource(url="https://example.test/catalog"), cache_dir=tmp_path / "cache")

    async def fetch(url, timeout):
        return [{"plugin_id": "example"}]

    monkeypatch.setattr(store_module, "get_json", fetch)
    result = await store.fetch()
    assert result.data == [{"plugin_id": "example"}]
    assert result.cache_file is None
    assert not store.cache_dir.exists()


@pytest.mark.asyncio
async def test_cache_write_failure_is_not_treated_as_remote_failure(cached_store, monkeypatch):
    store, cached = cached_store

    async def fetch(url, timeout):
        return {"plugins": [{"plugin_id": "remote"}]}

    def fail_write(*args, **kwargs):
        raise OSError("cache is read-only")

    monkeypatch.setattr(store_module, "get_json", fetch)
    monkeypatch.setattr(store_module.Path, "write_text", fail_write)
    with pytest.raises(OSError, match="read-only"):
        await store.fetch(
            force_refresh=True,
            persist_cache=True, allow_cache_fallback=True,
        )
    assert json.loads((store.cache_dir / "catalog.json").read_text(encoding="utf-8")) == cached


@pytest.mark.asyncio
async def test_source_refresh_failure_keeps_existing_cache(cached_store, monkeypatch):
    store, cached = cached_store

    async def fail_fetch(url, timeout):
        raise ConnectionError("source unavailable")

    monkeypatch.setattr(store_module, "get_json", fail_fetch)
    assert await store.refresh_cache() is None
    assert json.loads((store.cache_dir / "catalog.json").read_text(encoding="utf-8")) == cached

@pytest.mark.asyncio
async def test_store_instances_keep_sources_and_database_metadata_separate(tmp_path, monkeypatch):
    records = [
        {"id": "a", "name": "Source A", "url": "https://a.test/catalog", "cache_file": "a.json", "updated_at": 0},
        {"id": "b", "name": "Source B", "url": "https://b.test/catalog", "cache_file": "b.json", "updated_at": 0},
    ]
    sources = [StoreSource.from_record(record) for record in records]
    for source in sources:
        (tmp_path / source.cache_file).write_text('{"plugins": []}', encoding="utf-8")
    requests = []

    async def fetch(url, timeout):
        requests.append(url)
        return {"meta": {"source": url}, "plugins": []}

    monkeypatch.setattr(store_module, "get_json", fetch)
    monkeypatch.setattr(store_module.time, "time", lambda: 1000)
    stores = [PluginStore(source, cache_dir=tmp_path) for source in sources]
    for store, source in zip(stores, sources):
        result = await store.fetch(persist_cache=True)
        assert result.cache_file == source.cache_file
        assert result.updated_at == 1000
        assert result.data["meta"]["source"] == source.url
        assert json.loads((tmp_path / source.cache_file).read_text(encoding="utf-8")) == result.data
        assert await store.read_cache() == result.data
        assert source.updated_at == 0
    assert requests == [source.url for source in sources]
    assert [record["updated_at"] for record in records] == [0, 0]
    records[0]["name"] = "Renamed Source"
    assert sources[0].name == "Source A"
    assert StoreSource.from_record(records[0]).name == "Renamed Source"
