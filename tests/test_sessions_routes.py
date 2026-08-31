from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException

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
