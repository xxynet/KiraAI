from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from webui.routes.sessions import SessionsRoutes


class _SessionManager:
    def __init__(self):
        self.chat_memory = {}
        self.mutations = []

    def write_memory(self, session_id, messages):
        self.mutations.append(("messages", session_id, messages))

    def update_session_info(self, session_id, title=None, description=None):
        self.mutations.append(("info", session_id, title, description))

    def update_session_capabilities(self, session_id, capabilities):
        self.mutations.append(("capabilities", session_id, capabilities))

    def get_existing_memory_snapshot(self, session_id):
        session_data = self.chat_memory.get(session_id)
        if session_data is None:
            return None
        return session_data.get("memory", [])


@pytest.mark.asyncio
async def test_update_session_validates_capabilities_before_mutation():
    session_manager = _SessionManager()
    routes = SessionsRoutes(
        FastAPI(), SimpleNamespace(session_manager=session_manager)
    )

    with pytest.raises(HTTPException, match="Invalid capability group") as exc_info:
        await routes.update_session(
            "adapter:dm:user",
            {
                "messages": [],
                "title": "Updated title",
                "capabilities": {"image_recognition": None},
            },
        )

    assert exc_info.value.status_code == 400
    assert session_manager.mutations == []


def _make_routes(session_manager):
    return SessionsRoutes(
        FastAPI(), SimpleNamespace(session_manager=session_manager)
    )


@pytest.mark.asyncio
async def test_get_session_returns_404_for_missing_session():
    session_manager = _SessionManager()
    routes = _make_routes(session_manager)

    with pytest.raises(HTTPException) as exc_info:
        await routes.get_session("adapter:dm:missing")

    assert exc_info.value.status_code == 404
    assert session_manager.chat_memory == {}


@pytest.mark.asyncio
async def test_get_session_returns_existing_memory():
    session_manager = _SessionManager()
    session_manager.chat_memory["adapter:dm:user"] = {
        "title": "Title",
        "memory": [[{"role": "user", "content": "hi"}]],
    }
    routes = _make_routes(session_manager)

    result = await routes.get_session("adapter:dm:user")

    assert result["title"] == "Title"
    assert result["messages"] == [[{"role": "user", "content": "hi"}]]


@pytest.mark.asyncio
async def test_get_session_rejects_invalid_session_id():
    routes = _make_routes(_SessionManager())

    with pytest.raises(HTTPException) as exc_info:
        await routes.get_session("not-a-session-id")

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_list_sessions_skips_malformed_history_ids():
    session_manager = _SessionManager()
    session_manager.chat_memory = {
        "malformed-memory-id": {},
        "adapter:dm:existing": {"title": "Existing"},
    }
    session_manager.get_memory_count = lambda _: 1
    history = SimpleNamespace(list_sessions=AsyncMock(return_value=[
        {"session_id": "", "message_count": 1},
        {"session_id": "invalid", "message_count": 1},
        {"session_id": "adapter:user", "message_count": 1},
        {"session_id": "adapter:dm:existing", "message_count": 2},
        {"session_id": "adapter:dm:target:with:colons", "message_count": 3},
    ]))
    app = FastAPI()
    routes = SessionsRoutes(app, SimpleNamespace(
        session_manager=session_manager,
        message_processor=SimpleNamespace(message_history=history),
    ))
    app.add_api_route("/api/sessions", routes.list_sessions, methods=["GET"])
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test",
    ) as client:
        response = await client.get("/api/sessions")

    assert response.status_code == 200
    sessions = response.json()["sessions"]
    assert [item["id"] for item in sessions] == [
        "adapter:dm:existing", "adapter:dm:target:with:colons",
    ]
    assert sessions[0]["title"] == "Existing"
    assert sessions[0]["message_count"] == 1
    assert sessions[0]["history_count"] == 2
    assert sessions[1]["session_id"] == "target:with:colons"
    assert sessions[1]["history_count"] == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("record", [42, None, "malformed"])
@pytest.mark.parametrize("include_history", [False, True])
async def test_session_reads_skip_malformed_records_without_changing_storage(
    tmp_path, monkeypatch, record, include_history,
):
    import json
    from unittest.mock import Mock

    import core.chat.session_manager as session_manager_module

    path = tmp_path / "chat_memory.json"
    path.write_text(json.dumps({
        "adapter:dm:bad": record,
        "adapter:dm:good": {"title": "Good", "memory": []},
    }), encoding="utf-8")
    monkeypatch.setattr(session_manager_module, "CHAT_MEMORY_PATH", str(path))
    monkeypatch.setattr(session_manager_module, "logger", Mock())
    manager = session_manager_module.SessionManager(Mock(), Mock())
    saved = path.read_bytes()
    history = SimpleNamespace(list_sessions=AsyncMock(return_value=[
        {"session_id": "adapter:dm:bad", "message_count": 2},
        {"session_id": "adapter:dm:good", "message_count": 3},
        {"session_id": "adapter:dm:archive-only", "message_count": 1},
    ])) if include_history else None
    app = FastAPI()
    routes = SessionsRoutes(app, SimpleNamespace(
        session_manager=manager,
        message_processor=SimpleNamespace(message_history=history),
    ))
    app.add_api_route("/api/sessions", routes.list_sessions, methods=["GET"])
    app.add_api_route("/api/sessions/{session_id:path}", routes.get_session, methods=["GET"])
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test",
    ) as client:
        listing = await client.get("/api/sessions")
        malformed = await client.get("/api/sessions/adapter:dm:bad")
        healthy = await client.get("/api/sessions/adapter:dm:good")

    assert listing.status_code == 200
    sessions = listing.json()["sessions"]
    expected_ids = ["adapter:dm:good"]
    if include_history:
        expected_ids.append("adapter:dm:archive-only")
        assert sessions[0]["history_count"] == 3
    assert [item["id"] for item in sessions] == expected_ids
    assert sessions[0]["title"] == "Good"
    assert malformed.status_code == 404
    assert healthy.status_code == 200
    assert manager.chat_memory["adapter:dm:bad"] == record
    assert path.read_bytes() == saved
