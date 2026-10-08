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
