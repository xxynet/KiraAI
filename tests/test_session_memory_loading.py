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
