from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text

from core.db.db_mgr import DatabaseManager
from core.db.migrate_to_db import migrate_persona_chat_rules
from core.db.service import DatabaseService
from core.persona.model import PersonaInfo
from core.persona.persona_manager import PersonaManager
from core.prompt_manager import PromptManager
from tests.test_prompt_manager import CHAT_ENV, make_config
from webui.routes.auth import require_auth
from webui.routes.personas import PersonasRoutes


@pytest.fixture
async def rules_manager():
    database = DatabaseManager("sqlite+aiosqlite:///:memory:")
    await database.init()
    service = DatabaseService(database)
    await service.init_tables()
    manager = PersonaManager(service)
    await manager.init_persona()
    yield manager
    await database.dispose()


@pytest.mark.anyio
async def test_rules_are_persisted_separately_and_partial_updates_preserve_them(rules_manager):
    await rules_manager.create_persona(PersonaInfo(
        id="with-rules", name="Character", format="text",
        content="Character identity", chat_rules="Use short replies",
    ))
    await rules_manager.set_active_persona("with-rules")
    persona = await rules_manager.get_persona()
    assert persona.content == "Character identity"
    assert persona.chat_rules == "Use short replies"
    assert (await rules_manager.list_personas())[-1].chat_rules == "Use short replies"
    await rules_manager.update_persona(PersonaInfo(id=persona.id, content="Updated identity"))
    assert (await rules_manager.get_persona()).chat_rules == "Use short replies"
    await rules_manager.update_persona(PersonaInfo(id=persona.id, chat_rules=""))
    persona = await rules_manager.get_persona()
    assert persona.chat_rules == ""
    assert persona.content == "Updated identity"
    assert (await rules_manager.get_persona("default")).chat_rules == ""


@pytest.mark.anyio
async def test_rules_api_round_trip_and_older_clients(rules_manager):
    app = FastAPI()
    PersonasRoutes(app, SimpleNamespace(persona_manager=rules_manager)).register()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        payload = {"name": "Character", "format": "text", "content": "Identity", "chat_rules": "Short replies"}
        assert (await client.post("/api/personas", json=payload)).status_code == 401
        app.dependency_overrides[require_auth] = lambda: "admin"
        created = await client.post("/api/personas", json=payload)
        assert created.status_code == 201
        persona_id = created.json()["id"]
        endpoint = f"/api/personas/{persona_id}"
        assert created.json()["chat_rules"] == payload["chat_rules"]
        assert (await client.get(endpoint)).json()["chat_rules"] == payload["chat_rules"]
        await client.put("/api/personas/active", json={"persona_id": persona_id})
        assert (await client.get("/api/personas/active")).json()["chat_rules"] == payload["chat_rules"]
        personas = (await client.get("/api/personas")).json()
        assert next(p for p in personas if p["id"] == persona_id)["chat_rules"] == payload["chat_rules"]
        assert (await client.get("/api/personas/current/content")).json()["content"] == "Identity"
        payload["chat_rules"] = "Use emojis"
        assert (await client.put(endpoint, json=payload)).json()["chat_rules"] == "Use emojis"
        del payload["chat_rules"]
        assert (await client.put(endpoint, json=payload)).json()["chat_rules"] == "Use emojis"
        payload["chat_rules"] = ""
        assert (await client.put(endpoint, json=payload)).json()["chat_rules"] == ""
        assert (await rules_manager.get_persona(persona_id)).content == "Identity"
        older_client = await client.post("/api/personas", json={"name": "Legacy", "content": "Old"})
        assert older_client.status_code == 201
        assert older_client.json()["chat_rules"] == ""
        await rules_manager.update_persona(PersonaInfo(id="default", chat_rules="Keep default rules"))
        assert (await client.put("/api/personas/current/content", json={"content": "New default"})).status_code == 200
        assert (await rules_manager.get_persona("default")).chat_rules == "Keep default rules"


@pytest.mark.anyio
@pytest.mark.parametrize("lang", ["en", "zh"])
async def test_normal_chat_uses_active_rules_without_merging_or_rendering_them(rules_manager, lang):
    rules = 'Send {{literal}} and <emoji>1234</emoji>, with {"key": "value"}.'
    await rules_manager.create_persona(PersonaInfo(
        id="chat", name="Chat", format="text", content="Character identity", chat_rules=rules,
    ))
    await rules_manager.set_active_persona("chat")
    manager = PromptManager(make_config(lang), rules_manager)
    prompts = await manager.get_agent_prompt(CHAT_ENV)
    rule_prompt = next(prompt for prompt in prompts if prompt.name == "chat_rules")
    assert rule_prompt.source == "system"
    assert rule_prompt.to_string() == rules + "\n\n"
    assert [prompt.name for prompt in prompts][:3] == ["role", "persona", "chat_rules"]
    assert rules not in next(prompt for prompt in prompts if prompt.name == "persona").to_string()
    assert (await rules_manager.get_persona()).content == "Character identity"
    await rules_manager.set_active_persona("default")
    assert not any(prompt.name == "chat_rules" for prompt in await manager.get_agent_prompt(CHAT_ENV))


@pytest.mark.anyio
async def test_legacy_schema_adds_empty_rules_and_migration_is_idempotent():
    database = DatabaseManager("sqlite+aiosqlite:///:memory:")
    await database.init()
    service = DatabaseService(database)
    try:
        async with database.engine.begin() as conn:
            await conn.execute(text(
                "CREATE TABLE personas (id TEXT PRIMARY KEY, name TEXT NOT NULL, format TEXT NOT NULL, "
                "content TEXT NOT NULL, created_at BIGINT NOT NULL, is_active BOOLEAN, reference_image_path TEXT)"
            ))
            await conn.execute(text(
                "INSERT INTO personas VALUES ('legacy', 'Old', 'text', 'Identity and old rules', 1, 1, "
                "'selfie_refs/legacy.png')"
            ))
        await migrate_persona_chat_rules(service)
        persona = await service.get_active_persona()
        assert persona["chat_rules"] == ""
        assert persona["content"] == "Identity and old rules"
        assert persona["reference_image_path"] == "selfie_refs/legacy.png"
        await service.update_persona("legacy", chat_rules="New rules")
        await migrate_persona_chat_rules(service)
        assert (await service.get_persona("legacy"))["chat_rules"] == "New rules"
    finally:
        await database.dispose()


@pytest.mark.anyio
async def test_scoped_rules_api_persistence_and_independent_updates(rules_manager):
    app = FastAPI()
    PersonasRoutes(app, SimpleNamespace(persona_manager=rules_manager)).register()
    app.dependency_overrides[require_auth] = lambda: "admin"
    rules = {"chat_rules": "Global", "private_chat_rules": "Private", "group_chat_rules": "Group"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        payload = {"name": "Scoped", "format": "text", "content": "Identity", **rules}
        created = await client.post("/api/personas", json=payload)
        assert created.status_code == 201
        persona_id = created.json()["id"]
        endpoint = f"/api/personas/{persona_id}"
        await client.put("/api/personas/active", json={"persona_id": persona_id})
        responses = [
            created.json(), (await client.get(endpoint)).json(),
            (await client.get("/api/personas/active")).json(),
            next(p for p in (await client.get("/api/personas")).json() if p["id"] == persona_id),
        ]
        for response in responses:
            assert {key: response[key] for key in rules} == rules
        await rules_manager.update_persona(PersonaInfo(id=persona_id, content="Updated identity"))
        persona = await rules_manager.get_persona()
        assert {key: getattr(persona, key) for key in rules} == rules
        for key in rules:
            update = {"name": "Scoped", "content": "Updated identity", key: ""}
            response = await client.put(endpoint, json=update)
            assert response.status_code == 200
            rules[key] = ""
            assert {field: response.json()[field] for field in rules} == rules
            assert response.json()["content"] == "Updated identity"


@pytest.mark.anyio
@pytest.mark.parametrize("chat_type,scoped", [
    ("DirectMessage", "Private only"), ("GroupMessage", "Group only"),
    ("Unknown", ""), (None, ""),
])
@pytest.mark.parametrize("global_rule", ["Global {{literal}}", ""])
async def test_prompt_selects_only_matching_scope(rules_manager, chat_type, scoped, global_rule):
    await rules_manager.update_persona(PersonaInfo(
        id="default", content="Identity", chat_rules=global_rule,
        private_chat_rules="Private only", group_chat_rules="Group only",
    ))
    manager = PromptManager(make_config("zh"), rules_manager)
    prompts = await manager.get_agent_prompt({**CHAT_ENV, "chat_type": chat_type})
    rule_prompts = [prompt for prompt in prompts if prompt.name == "chat_rules"]
    expected = "\n\n".join(rule for rule in (global_rule, scoped) if rule)
    if expected:
        assert len(rule_prompts) == 1
        assert rule_prompts[0].to_string() == expected + "\n\n"
    else:
        assert not rule_prompts
    assert (await rules_manager.get_persona()).content == "Identity"


@pytest.mark.anyio
async def test_existing_global_rules_survive_scoped_column_upgrade():
    database = DatabaseManager("sqlite+aiosqlite:///:memory:")
    await database.init()
    service = DatabaseService(database)
    try:
        async with database.engine.begin() as conn:
            await conn.execute(text(
                "CREATE TABLE personas (id TEXT PRIMARY KEY, name TEXT NOT NULL, format TEXT NOT NULL, "
                "content TEXT NOT NULL, created_at BIGINT NOT NULL, is_active BOOLEAN, "
                "reference_image_path TEXT, chat_rules TEXT NOT NULL DEFAULT '')"
            ))
            await conn.execute(text(
                "INSERT INTO personas VALUES ('existing', 'Old', 'text', 'Identity', 1, 1, NULL, 'Global')"
            ))
        await migrate_persona_chat_rules(service)
        persona = await service.get_active_persona()
        assert persona["chat_rules"] == "Global"
        assert persona["private_chat_rules"] == ""
        assert persona["group_chat_rules"] == ""
        await service.update_persona("existing", private_chat_rules="Private", group_chat_rules="Group")
        await migrate_persona_chat_rules(service)
        persona = await service.get_persona("existing")
        assert persona["private_chat_rules"] == "Private"
        assert persona["group_chat_rules"] == "Group"
    finally:
        await database.dispose()
