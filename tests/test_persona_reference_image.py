import importlib
import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from PIL import Image
from sqlalchemy import text

from core.config import config_loader
from core.db.db_mgr import DatabaseManager
from core.db import migrate_to_db
from core.db.service import DatabaseService
from core.persona.model import PersonaInfo
from core.persona.persona_manager import PersonaManager
from core.persona import reference_image
from webui.routes.auth import require_auth
from webui.routes.personas import PersonasRoutes


def image_bytes(image_format="PNG", color="red"):
    output = BytesIO()
    Image.new("RGB", (16, 16), color).save(output, format=image_format)
    return output.getvalue()


@pytest.fixture
async def image_manager(tmp_path, monkeypatch):
    monkeypatch.setattr(reference_image, "get_data_path", lambda: tmp_path / "data")
    database = DatabaseManager("sqlite+aiosqlite:///:memory:")
    await database.init()
    service = DatabaseService(database)
    await service.init_tables()
    manager = PersonaManager(service)
    await manager.create_persona(PersonaInfo(id="p1", name="First", content="Original"))
    await manager.create_persona(PersonaInfo(id="p2", name="Second", content="Other"))
    yield manager
    await database.dispose()


@pytest.mark.anyio
async def test_reference_image_replacement_preserves_extension_and_isolates_personas(image_manager):
    manager = image_manager
    original = await manager.set_reference_image("p1", image_bytes(), "portrait.PNG")
    other = await manager.set_reference_image("p2", image_bytes(), "other.png")
    assert original.name == "p1.PNG"
    assert original.parent.name == "selfie_refs"
    assert original.read_bytes() == image_bytes()
    replacement = await manager.set_reference_image("p1", image_bytes("JPEG"), "replacement.jpeg")
    assert replacement.name == "p1.jpeg"
    assert not original.exists()
    assert other.exists()
    assert await manager.get_reference_image("p1") == replacement
    assert (await manager.get_persona("p1")).content == "Original"
    await manager.set_active_persona("p1")
    assert await manager.get_reference_image() == replacement


@pytest.mark.anyio
async def test_reference_image_same_extension_replaces_bytes(image_manager):
    first = await image_manager.set_reference_image("p1", image_bytes(), "first.png")
    replacement_bytes = image_bytes(color="blue")
    second = await image_manager.set_reference_image("p1", replacement_bytes, "second.png")
    assert first == second
    assert second.read_bytes() == replacement_bytes
    assert list(second.parent.iterdir()) == [second]


@pytest.mark.anyio
async def test_reference_image_delete_and_active_persona_guard(image_manager):
    path = await image_manager.set_reference_image("p1", image_bytes(), "portrait.png")
    await image_manager.set_active_persona("p1")
    with pytest.raises(ValueError, match="active persona"):
        await image_manager.delete_persona("p1")
    assert path.exists()
    await image_manager.set_active_persona("p2")
    assert await image_manager.delete_persona("p1")
    assert not path.exists()
    assert await image_manager.get_reference_image("p1") is None


@pytest.mark.anyio
async def test_missing_persona_image_cannot_be_saved(image_manager):
    assert await image_manager.get_reference_image("missing") is None
    assert await image_manager.get_reference_image("p1") is None
    with pytest.raises(LookupError):
        await image_manager.set_reference_image("missing", image_bytes(), "image.png")


@pytest.mark.anyio
@pytest.mark.parametrize("filename,content", [
    ("image.svg", b"<svg></svg>"),
    ("image.png", b"not an image"),
    ("image.jpg", image_bytes()),
    ("image.png", b""),
])
async def test_invalid_upload_keeps_existing_image(image_manager, filename, content):
    original = await image_manager.set_reference_image("p1", image_bytes(), "original.png")
    with pytest.raises(ValueError):
        await image_manager.set_reference_image("p1", content, filename)
    assert original.read_bytes() == image_bytes()
    assert list(original.parent.iterdir()) == [original]


@pytest.mark.parametrize("persona_id", ["../outside", "a/b", "a\\b", "p1:stream", "..", "CON", "CON.txt", "NUL", "trailing."])
def test_reference_image_rejects_unsafe_ids(tmp_path, monkeypatch, persona_id):
    monkeypatch.setattr(reference_image, "get_data_path", lambda: tmp_path)
    with pytest.raises(ValueError):
        reference_image.save_reference_image(persona_id, image_bytes(), "image.png")
    assert not list(tmp_path.iterdir())


@pytest.mark.anyio
async def test_reference_image_api_auth_upload_preview_and_errors(image_manager, monkeypatch):
    app = FastAPI()
    PersonasRoutes(app, SimpleNamespace(persona_manager=image_manager)).register()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        endpoint = "/api/personas/p1/reference-image"
        assert (await client.get(endpoint)).status_code == 401
        assert (await client.put(endpoint, files={"file": ("image.png", image_bytes(), "image/png")})).status_code == 401
        app.dependency_overrides[require_auth] = lambda: "admin"
        assert (await client.get(endpoint)).status_code == 404
        response = await client.put(endpoint, files={"file": ("portrait.PNG", image_bytes(), "image/png")})
        assert response.status_code == 200
        assert response.json() == {"filename": "p1.PNG"}
        preview = await client.get(endpoint)
        assert preview.status_code == 200
        assert preview.content == image_bytes()
        assert preview.headers["content-type"] == "image/png"
        assert preview.headers["cache-control"] == "no-store"
        invalid = await client.put(endpoint, files={"file": ("invalid.png", b"invalid", "image/png")})
        assert invalid.status_code == 400
        missing = await client.put("/api/personas/missing/reference-image", files={"file": ("image.png", image_bytes(), "image/png")})
        assert missing.status_code == 404
        monkeypatch.setattr("webui.routes.personas.MAX_REFERENCE_IMAGE_BYTES", 4)
        oversized = await client.put(endpoint, files={"file": ("image.png", image_bytes(), "image/png")})
        assert oversized.status_code == 413
        assert (await client.get(endpoint)).content == image_bytes()

@pytest.mark.anyio
@pytest.mark.parametrize("extension,image_format", [(".jpg", "JPEG"), (".webp", "WEBP"), (".gif", "GIF")])
async def test_reference_image_supported_formats(image_manager, extension, image_format):
    data = image_bytes(image_format)
    path = await image_manager.set_reference_image("p1", data, "portrait" + extension)
    assert path.name == "p1" + extension
    assert path.read_bytes() == data


@pytest.mark.anyio
async def test_reference_image_failed_write_preserves_original(image_manager, monkeypatch):
    original = await image_manager.set_reference_image("p1", image_bytes(), "original.png")

    def fail_replace(*args):
        raise OSError("Simulated write failure")

    monkeypatch.setattr(reference_image.os, "replace", fail_replace)
    with pytest.raises(OSError, match="Simulated"):
        await image_manager.set_reference_image("p1", image_bytes("JPEG"), "replacement.jpg")
    assert original.read_bytes() == image_bytes()
    assert list(original.parent.iterdir()) == [original]

@pytest.mark.anyio
async def test_reference_image_path_persisted_and_crud_preserves_it(image_manager):
    path = await image_manager.set_reference_image("p1", image_bytes(), "portrait.PNG")
    expected = "selfie_refs/p1.PNG"
    assert (await image_manager.db.get_persona("p1"))["reference_image_path"] == expected
    await image_manager.update_persona(PersonaInfo(id="p1", name="Renamed", content="Updated", format="markdown"))
    assert (await image_manager.get_persona("p1")).reference_image_path == expected
    assert next(p for p in await image_manager.list_personas() if p.id == "p1").reference_image_path == expected
    await image_manager.set_active_persona("p1")
    assert (await image_manager.get_active_persona()).reference_image_path == expected
    assert await image_manager.get_reference_image() == path
    fresh_manager = PersonaManager(image_manager.db)
    assert await fresh_manager.get_reference_image("p1") == path
    routes = PersonasRoutes(None, SimpleNamespace(persona_manager=fresh_manager))
    assert (await routes.get_persona("p1")).reference_image_path == expected
    assert (await routes.get_active_persona()).reference_image_path == expected
    assert next(p for p in await routes.list_personas() if p.id == "p1").reference_image_path == expected


@pytest.mark.anyio
async def test_reference_image_operations_do_not_scan_directory(image_manager, monkeypatch):
    path = await image_manager.set_reference_image("p1", image_bytes(), "portrait.png")

    def forbid_scan(*args):
        raise AssertionError("Reference image operations must not scan directories")

    monkeypatch.setattr(Path, "iterdir", forbid_scan)
    assert await image_manager.get_reference_image("p1") == path
    replacement = await image_manager.set_reference_image("p1", image_bytes("JPEG"), "portrait.jpg")
    assert not path.exists()
    assert await image_manager.get_reference_image("p1") == replacement
    assert (await image_manager.get_persona("p1")).reference_image_path == "selfie_refs/p1.jpg"
    assert await image_manager.delete_persona("p1")
    assert not replacement.exists()


@pytest.mark.anyio
async def test_reference_image_missing_file_has_no_directory_fallback(image_manager):
    path = await image_manager.set_reference_image("p1", image_bytes(), "portrait.png")
    path.unlink()
    (path.parent / "p1.jpg").write_bytes(image_bytes("JPEG"))
    assert await image_manager.get_reference_image("p1") is None
    assert (await image_manager.get_persona("p1")).reference_image_path == "selfie_refs/p1.png"


@pytest.mark.anyio
@pytest.mark.parametrize("extension,image_format", [(".png", "PNG"), (".jpg", "JPEG")])
async def test_reference_image_failed_database_update_restores_old_file(image_manager, monkeypatch, extension, image_format):
    path = await image_manager.set_reference_image("p1", image_bytes(), "old.png")

    async def fail_update(*args, **kwargs):
        raise RuntimeError("Simulated database failure")

    monkeypatch.setattr(image_manager.db, "update_persona", fail_update)
    with pytest.raises(RuntimeError, match="database failure"):
        await image_manager.set_reference_image("p1", image_bytes(image_format, "blue"), "new" + extension)
    assert path.read_bytes() == image_bytes()
    assert list(path.parent.iterdir()) == [path]
    assert (await image_manager.get_persona("p1")).reference_image_path == "selfie_refs/p1.png"


@pytest.mark.parametrize("stored_path", ["../outside.png", "selfie_refs/p2.png", "selfie_refs/p1.txt", "selfie_refs/../p1.png"])
def test_recorded_reference_image_path_rejects_invalid_locations(stored_path):
    with pytest.raises(ValueError):
        reference_image.get_reference_image_path("p1", stored_path)


@pytest.fixture
async def legacy_image_database(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    directory = data_dir / "selfie_refs"
    directory.mkdir(parents=True)
    (directory / "p1.PNG").write_bytes(image_bytes())
    (directory / "unknown.png").write_bytes(image_bytes())
    (directory / "p2.txt").write_text("Not an image", encoding="utf-8")
    monkeypatch.setattr(reference_image, "get_data_path", lambda: data_dir)
    monkeypatch.setattr(migrate_to_db, "get_data_path", lambda: data_dir)
    database = DatabaseManager(f"sqlite+aiosqlite:///{tmp_path / 'legacy.db'}")
    await database.init()
    async with database.engine.begin() as conn:
        await conn.execute(text("CREATE TABLE personas (id TEXT PRIMARY KEY, name TEXT NOT NULL, format TEXT NOT NULL, content TEXT NOT NULL, created_at BIGINT NOT NULL, is_active BOOLEAN)"))
        await conn.execute(text("INSERT INTO personas VALUES ('p1', 'First', 'text', 'Original', 1, 1), ('p2', 'Second', 'text', 'Other', 2, 0)"))
    yield DatabaseService(database), directory
    await database.dispose()


@pytest.mark.anyio
async def test_reference_image_schema_migration_does_not_scan_or_backfill(legacy_image_database, monkeypatch):
    service, directory = legacy_image_database

    def forbid_scan(*args):
        raise AssertionError("Intermediate selfie_refs files must not be scanned")

    monkeypatch.setattr(Path, "iterdir", forbid_scan)
    await migrate_to_db.migrate_persona_reference_image_path(service)
    await migrate_to_db.migrate_persona_reference_image_path(service)
    first = await service.get_persona("p1")
    assert first["content"] == "Original"
    assert first["is_active"] is True
    assert first["reference_image_path"] is None
    assert (await service.get_persona("p2"))["reference_image_path"] is None
    assert (directory / "p1.PNG").read_bytes() == image_bytes()
    assert await PersonaManager(service).get_reference_image("p1") is None


@pytest.fixture
def legacy_selfie_config(tmp_path, monkeypatch):
    config_path = tmp_path / "system_config.json"
    monkeypatch.setattr(config_loader, "CONFIG_PATH", config_path)
    monkeypatch.setattr(migrate_to_db, "get_data_path", lambda: tmp_path / "data")

    def create(path):
        config_path.write_text(json.dumps({
            "bot_config": {"selfie": {"path": path}, "agent": {"max_tool_loop": 5}},
        }), encoding="utf-8")
        return config_loader.KiraConfig(default_config={"bot_config": {}}), config_path

    return create


@pytest.mark.anyio
@pytest.mark.parametrize("path_style", ["absolute", "relative", "data_prefix", "backslashes"])
async def test_configured_selfie_migration_copies_to_active_persona_once(
    image_manager, legacy_selfie_config, tmp_path, monkeypatch, path_style,
):
    source = tmp_path / "data" / "old" / "portrait.PNG"
    source.parent.mkdir(parents=True)
    source.write_bytes(image_bytes())
    configured_path = {
        "absolute": str(source), "relative": "old/portrait.PNG",
        "data_prefix": "data/old/portrait.PNG", "backslashes": r"data\old\portrait.PNG",
    }[path_style]
    config, config_path = legacy_selfie_config(configured_path)
    await image_manager.set_active_persona("p2")

    def forbid_scan(*args):
        raise AssertionError("Legacy config migration must not scan selfie_refs")

    monkeypatch.setattr(Path, "iterdir", forbid_scan)
    await migrate_to_db.migrate_selfie_reference_image(image_manager, config)
    expected_path = source.parent.parent / "selfie_refs" / "p2.PNG"
    assert source.read_bytes() == image_bytes()
    assert expected_path.read_bytes() == image_bytes()
    assert (await image_manager.get_persona("p2")).reference_image_path == "selfie_refs/p2.PNG"
    assert (await image_manager.get_persona("p1")).reference_image_path is None
    assert (await image_manager.get_persona("p2")).content == "Other"
    assert await image_manager.get_reference_image() == expected_path
    saved_config = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved_config == {"bot_config": {"agent": {"max_tool_loop": 5}}}
    assert "selfie" not in config["bot_config"]
    await image_manager.set_active_persona("p1")
    await migrate_to_db.migrate_selfie_reference_image(image_manager, config)
    assert (await image_manager.get_persona("p1")).reference_image_path is None


@pytest.mark.anyio
@pytest.mark.parametrize("extension,image_format", [(".jpg", "JPEG"), (".WebP", "WEBP"), (".gif", "GIF")])
async def test_configured_selfie_migration_preserves_original_extension(
    image_manager, legacy_selfie_config, tmp_path, extension, image_format,
):
    source = tmp_path / ("portrait" + extension)
    source.write_bytes(image_bytes(image_format))
    config, _ = legacy_selfie_config(str(source))
    await image_manager.set_active_persona("p1")
    await migrate_to_db.migrate_selfie_reference_image(image_manager, config)
    path = await image_manager.get_reference_image()
    assert path.name == "p1" + extension
    assert path.read_bytes() == source.read_bytes()


@pytest.mark.anyio
async def test_configured_selfie_migration_preserves_existing_persona_reference(
    image_manager, legacy_selfie_config, tmp_path, monkeypatch,
):
    existing = await image_manager.set_reference_image("p1", image_bytes("JPEG"), "selected.jpg")
    await image_manager.set_active_persona("p1")
    config, config_path = legacy_selfie_config(str(tmp_path / "missing-old.png"))

    def forbid_read(*args):
        raise AssertionError("Existing persona selection must take precedence")

    monkeypatch.setattr(migrate_to_db, "_read_configured_selfie_image", forbid_read)
    await migrate_to_db.migrate_selfie_reference_image(image_manager, config)
    assert await image_manager.get_reference_image() == existing
    assert existing.read_bytes() == image_bytes("JPEG")
    assert "selfie" not in json.loads(config_path.read_text())["bot_config"]


@pytest.mark.anyio
@pytest.mark.parametrize("source_state", ["missing", "invalid", "database_failure", "write_failure"])
async def test_configured_selfie_migration_failure_preserves_source_and_can_retry(
    image_manager, legacy_selfie_config, tmp_path, monkeypatch, source_state,
):
    source = tmp_path / "portrait.png"
    if source_state != "missing":
        source.write_bytes(b"invalid" if source_state == "invalid" else image_bytes())
    config, config_path = legacy_selfie_config(str(source))
    await image_manager.set_active_persona("p1")
    original_update = image_manager.db.update_persona
    original_replace = reference_image.os.replace

    async def fail_update(*args, **kwargs):
        raise RuntimeError("Simulated database failure")

    def fail_replace(*args):
        raise OSError("Simulated write failure")

    if source_state == "database_failure":
        monkeypatch.setattr(image_manager.db, "update_persona", fail_update)
    elif source_state == "write_failure":
        monkeypatch.setattr(reference_image.os, "replace", fail_replace)
    await migrate_to_db.migrate_selfie_reference_image(image_manager, config)
    assert config["bot_config"]["selfie"]["path"] == str(source)
    assert json.loads(config_path.read_text())["bot_config"]["selfie"]["path"] == str(source)
    assert (await image_manager.get_persona("p1")).reference_image_path is None
    if source_state != "missing":
        assert source.read_bytes() == (b"invalid" if source_state == "invalid" else image_bytes())
    source.write_bytes(image_bytes())
    monkeypatch.setattr(image_manager.db, "update_persona", original_update)
    monkeypatch.setattr(reference_image.os, "replace", original_replace)
    await migrate_to_db.migrate_selfie_reference_image(image_manager, config)
    assert (await image_manager.get_reference_image()).read_bytes() == source.read_bytes()
    assert "selfie" not in config["bot_config"]


@pytest.mark.anyio
async def test_configured_selfie_migration_cleanup_failure_retries_without_copy(
    image_manager, legacy_selfie_config, tmp_path, monkeypatch,
):
    source = tmp_path / "portrait.png"
    source.write_bytes(image_bytes())
    config, config_path = legacy_selfie_config(str(source))
    await image_manager.set_active_persona("p1")
    original_save = config_loader.KiraConfig.save_config

    def fail_save(self, **kwargs):
        raise OSError("Simulated config save failure")

    monkeypatch.setattr(config_loader.KiraConfig, "save_config", fail_save)
    await migrate_to_db.migrate_selfie_reference_image(image_manager, config)
    migrated = await image_manager.get_reference_image()
    assert migrated.read_bytes() == source.read_bytes()
    assert config["bot_config"]["selfie"]["path"] == str(source)
    assert json.loads(config_path.read_text())["bot_config"]["selfie"]["path"] == str(source)

    def forbid_read(*args):
        raise AssertionError("Retry must not copy a persisted reference again")

    monkeypatch.setattr(migrate_to_db, "_read_configured_selfie_image", forbid_read)
    monkeypatch.setattr(config_loader.KiraConfig, "save_config", original_save)
    await migrate_to_db.migrate_selfie_reference_image(image_manager, config)
    assert "selfie" not in json.loads(config_path.read_text())["bot_config"]
    assert await image_manager.get_reference_image() == migrated


@pytest.mark.anyio
async def test_configured_selfie_migration_waits_for_active_persona(
    image_manager, legacy_selfie_config, tmp_path,
):
    source = tmp_path / "portrait.png"
    source.write_bytes(image_bytes())
    config, _ = legacy_selfie_config(str(source))
    await migrate_to_db.migrate_selfie_reference_image(image_manager, config)
    assert config["bot_config"]["selfie"]["path"] == str(source)
    assert (await image_manager.get_persona("p1")).reference_image_path is None
    await image_manager.set_active_persona("p1")
    await migrate_to_db.migrate_selfie_reference_image(image_manager, config)
    assert (await image_manager.get_persona("p1")).reference_image_path == "selfie_refs/p1.png"


@pytest.mark.anyio
async def test_configured_selfie_migration_works_after_default_persona_initialization(
    image_manager, legacy_selfie_config, tmp_path,
):
    await image_manager.delete_persona("p1")
    await image_manager.delete_persona("p2")
    source = tmp_path / "portrait.png"
    source.write_bytes(image_bytes())
    config, _ = legacy_selfie_config(str(source))
    await image_manager.init_persona()
    await migrate_to_db.migrate_selfie_reference_image(image_manager, config)
    assert (await image_manager.get_active_persona()).id == "default"
    assert (await image_manager.get_reference_image()).name == "default.png"


@pytest.mark.anyio
async def test_empty_legacy_selfie_config_is_removed(image_manager, legacy_selfie_config):
    config, config_path = legacy_selfie_config(None)
    await migrate_to_db.migrate_selfie_reference_image(image_manager, config)
    assert "selfie" not in config["bot_config"]
    assert "selfie" not in json.loads(config_path.read_text())["bot_config"]


@pytest.mark.anyio
async def test_selfie_tag_uses_current_persona_reference(image_manager, monkeypatch):
    tags = importlib.import_module("core.plugin.builtin_plugins.kira-ai.tags")
    first = await image_manager.set_reference_image("p1", image_bytes(), "first.png")
    second = await image_manager.set_reference_image("p2", image_bytes("JPEG"), "second.jpg")
    client = object()
    output = tags.Image(image="https://example.invalid/result.png")
    encode = AsyncMock(return_value="cmVmZXJlbmNl")
    generate = AsyncMock(return_value=output)
    monkeypatch.setattr(tags, "image_to_base64", encode)
    monkeypatch.setattr(tags, "image_to_image", generate)
    tag = tags.SelfieTag(SimpleNamespace(
        persona_mgr=image_manager,
        provider_mgr=SimpleNamespace(get_default_image=lambda: client),
    ))
    for persona_id, expected, mime in [("p1", first, "image/png"), ("p2", second, "image/jpeg")]:
        await image_manager.set_active_persona(persona_id)
        assert await tag.handle("the character smiling") == [output]
        encode.assert_awaited_with(str(expected))
        assert generate.await_args.args == (client, "the character smiling")
        reference = generate.await_args.kwargs["image"]
        assert reference.image == "cmVmZXJlbmNl"
        assert reference.name == expected.name
        assert reference.mime == mime


@pytest.mark.anyio
async def test_selfie_tag_missing_reference_does_not_generate(image_manager, monkeypatch):
    tags = importlib.import_module("core.plugin.builtin_plugins.kira-ai.tags")
    generate = AsyncMock()
    monkeypatch.setattr(tags, "image_to_image", generate)
    tag = tags.SelfieTag(SimpleNamespace(persona_mgr=image_manager))
    await image_manager.set_active_persona("p1")
    assert await tag.handle("the character smiling") == []
    generate.assert_not_awaited()
