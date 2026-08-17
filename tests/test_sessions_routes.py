from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException

from webui.routes.sessions import SessionsRoutes

SESSION_ID = "qq:private:10001"


class FakeSessionManager:
    """Mirrors SessionManager's create-on-access behaviour for chat_memory."""

    def __init__(self, sessions=None):
        self.chat_memory = dict(sessions or {})
        self.writes: list[tuple[str, list]] = []

    def _ensure_session_data(self, session):
        self.chat_memory.setdefault(
            session, {"title": "", "description": "", "timestamp": None, "memory": []},
        )

    def read_memory(self, session):
        self._ensure_session_data(session)
        return self.chat_memory[session]["memory"]

    def write_memory(self, session, memory):
        self._ensure_session_data(session)
        self.chat_memory[session]["memory"] = memory
        self.writes.append((session, memory))

    def update_session_info(self, session, title=None, description=None):
        self._ensure_session_data(session)


def make_routes(session_manager):
    return SessionsRoutes(FastAPI(), SimpleNamespace(session_manager=session_manager))


@pytest.mark.anyio
async def test_get_session_returns_404_without_creating_it():
    session_manager = FakeSessionManager()
    routes = make_routes(session_manager)

    with pytest.raises(HTTPException) as exc_info:
        await routes.get_session("qq:private:injected-by-attacker")

    assert exc_info.value.status_code == 404
    assert session_manager.chat_memory == {}


@pytest.mark.anyio
async def test_get_session_returns_existing_session():
    session_manager = FakeSessionManager({
        SESSION_ID: {
            "title": "Chat",
            "description": "desc",
            "timestamp": None,
            "memory": [[{"role": "user", "content": "hi"}]],
        },
    })

    result = await make_routes(session_manager).get_session(SESSION_ID)

    assert result["id"] == SESSION_ID
    assert result["adapter_name"] == "qq"
    assert result["session_type"] == "private"
    assert result["session_id"] == "10001"
    assert result["title"] == "Chat"
    assert result["messages"] == [[{"role": "user", "content": "hi"}]]


@pytest.mark.anyio
async def test_get_session_rejects_malformed_id():
    with pytest.raises(HTTPException) as exc_info:
        await make_routes(FakeSessionManager()).get_session("not-a-session")

    assert exc_info.value.status_code == 400


@pytest.mark.anyio
async def test_update_session_writes_memory():
    session_manager = FakeSessionManager()
    messages = [[{"role": "user", "content": "hello"}]]

    result = await make_routes(session_manager).update_session(SESSION_ID, {"messages": messages})

    assert result["messages"] == messages
    assert session_manager.writes == [(SESSION_ID, messages)]
