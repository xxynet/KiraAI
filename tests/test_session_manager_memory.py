import json
from pathlib import Path
from threading import Lock

from core.chat.session_manager import SessionManager

SESSION_ID = "qq:private:10001"


def make_manager(tmp_path: Path) -> SessionManager:
    """Build a SessionManager without touching the real data directory."""
    manager = object.__new__(SessionManager)
    manager.chat_memory = {}
    manager.chat_memory_path = str(tmp_path / "chat_memory.json")
    manager.memory_lock = Lock()
    manager.max_memory_length = 10
    return manager


def test_write_memory_creates_missing_session(tmp_path: Path) -> None:
    manager = make_manager(tmp_path)
    messages = [[{"role": "user", "content": "hello"}]]

    manager.write_memory(SESSION_ID, messages)

    assert manager.chat_memory[SESSION_ID]["memory"] == messages
    assert manager.chat_memory[SESSION_ID]["title"] == ""
    persisted = json.loads(Path(manager.chat_memory_path).read_text(encoding="utf-8"))
    assert persisted[SESSION_ID]["memory"] == messages


def test_write_memory_preserves_existing_metadata(tmp_path: Path) -> None:
    manager = make_manager(tmp_path)
    manager.chat_memory[SESSION_ID] = {
        "title": "Chat",
        "description": "desc",
        "timestamp": 123,
        "memory": [[{"role": "user", "content": "old"}]],
    }
    messages = [[{"role": "user", "content": "new"}]]

    manager.write_memory(SESSION_ID, messages)

    assert manager.chat_memory[SESSION_ID]["title"] == "Chat"
    assert manager.chat_memory[SESSION_ID]["timestamp"] == 123
    assert manager.chat_memory[SESSION_ID]["memory"] == messages
