import json
from unittest.mock import Mock

import pytest

import core.chat.session_manager as session_manager_module
from core.chat.session_manager import SessionManager


@pytest.mark.parametrize("memory, legacy", [
    (memory, legacy)
    for memory in (
        [[{"role": "invalid", "content": "private-content"}]],
        [{"role": "user", "content": "private-content"}],
        [[{"role": ["user"], "content": "private-content"}]],
        [["private-content"]],
        None,
    )
    for legacy in (False, True)
    if not legacy or isinstance(memory, list)
])
def test_startup_preserves_malformed_memory_and_normalizes_other_sessions(
    tmp_path, monkeypatch, memory, legacy,
):
    path = tmp_path / "chat_memory.json"
    bad_session = memory if legacy else {"title": "private-title", "memory": memory}
    original = {
        "adapter:dm:bad": bad_session,
        "adapter:dm:good": {"memory": [[{"role": "user", "content": "hello"}]]},
    }
    path.write_text(json.dumps(original), encoding="utf-8")
    monkeypatch.setattr(session_manager_module, "CHAT_MEMORY_PATH", str(path))
    logger = Mock()
    monkeypatch.setattr(session_manager_module, "logger", logger)

    manager = SessionManager(Mock(), Mock())
    assert manager.chat_memory["adapter:dm:bad"]["memory"] == memory
    saved = json.loads(path.read_text(encoding="utf-8"))
    if not legacy:
        assert saved["adapter:dm:bad"] == bad_session
    else:
        assert saved["adapter:dm:bad"]["memory"] == memory
    good = saved["adapter:dm:good"]["memory"][0][0]
    assert good["role"] == "user" and good["content"] == "hello"
    assert good["_extra"]["llm_message_id"]
    logger.warning.assert_called_once()
    assert "private-content" not in str(logger.mock_calls)
    assert "private-title" not in str(logger.mock_calls)

    # Repeated startup keeps both the raw memory and valid message identities.
    restarted = SessionManager(Mock(), Mock())
    assert restarted.chat_memory == manager.chat_memory


@pytest.mark.parametrize("record", [None, 42, "private-content"])
def test_startup_preserves_non_object_session_record(tmp_path, monkeypatch, record):
    path = tmp_path / "chat_memory.json"
    original = {"adapter:dm:bad": record, "adapter:dm:good": {"memory": []}}
    path.write_text(json.dumps(original), encoding="utf-8")
    monkeypatch.setattr(session_manager_module, "CHAT_MEMORY_PATH", str(path))
    monkeypatch.setattr(session_manager_module, "logger", Mock())

    manager = SessionManager(Mock(), Mock())
    assert manager.chat_memory == original
    assert json.loads(path.read_text(encoding="utf-8")) == original


def test_explicit_memory_edit_still_rejects_invalid_roles(tmp_path, monkeypatch):
    path = tmp_path / "chat_memory.json"
    monkeypatch.setattr(session_manager_module, "CHAT_MEMORY_PATH", str(path))
    manager = SessionManager(Mock(), Mock())
    manager.write_memory("adapter:dm:user", [[{"role": "user", "content": "original"}]])
    saved = path.read_bytes()

    with pytest.raises(ValueError):
        manager.write_memory("adapter:dm:user", [[{"role": "invalid", "content": "bad"}]])
    assert path.read_bytes() == saved


@pytest.mark.anyio
@pytest.mark.parametrize("old_memory", [
    [["bad"]],
    [{"role": "user", "content": "old"}],
    None,
    42,
    {"invalid": "memory"},
    [[{"role": ["user"], "_extra": {"llm_message_id": "bad-id"}}]],
])
@pytest.mark.parametrize("replacement", [[], [[{"role": "user", "content": "repaired"}]]])
async def test_api_can_replace_malformed_memory(tmp_path, monkeypatch, old_memory, replacement):
    from types import SimpleNamespace

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from webui.routes.sessions import SessionsRoutes

    path = tmp_path / "chat_memory.json"
    path.write_text(json.dumps({"adapter:dm:user": {"memory": old_memory}}), encoding="utf-8")
    monkeypatch.setattr(session_manager_module, "CHAT_MEMORY_PATH", str(path))
    monkeypatch.setattr(session_manager_module, "logger", Mock())
    manager = SessionManager(Mock(), Mock())
    app = FastAPI()
    routes = SessionsRoutes(app, SimpleNamespace(session_manager=manager))
    app.add_api_route("/api/sessions/{session_id:path}", routes.update_session, methods=["PUT"])

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test",
    ) as client:
        response = await client.put("/api/sessions/adapter:dm:user", json={"messages": replacement})

    assert response.status_code == 200
    saved = json.loads(path.read_text(encoding="utf-8"))["adapter:dm:user"]["memory"]
    assert saved == response.json()["messages"]
    if replacement:
        assert saved[0][0]["content"] == "repaired"
        assert saved[0][0]["_extra"]["llm_message_id"]
    else:
        assert saved == []


def test_repair_preserves_valid_ids_among_malformed_old_entries(tmp_path, monkeypatch):
    from core.chat.memory_metadata import normalize_memory

    valid = {"role": "user", "content": "original", "_extra": {"llm_message_id": "keep"}}
    old = [None, {"role": "assistant"}, ["bad", valid]]
    edited = [[{**valid, "content": "edited"}]]
    assert normalize_memory(edited, previous=old) == edited
    with pytest.raises(ValueError):
        normalize_memory([[{"role": ["user"], "content": "invalid"}]], previous=old)
