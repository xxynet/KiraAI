from __future__ import annotations

import asyncio
import copy
import json
import os
import time
import uuid
from typing import Dict, List, Optional, TYPE_CHECKING, overload
from threading import Lock

from core.logging_manager import get_logger
from core.config import KiraConfig
from core.utils.path_utils import get_data_path
from core.db.service import DatabaseService

from .session import Session

if TYPE_CHECKING:
    from core.event_bus import EventBus

logger = get_logger("session", "green")

CHAT_MEMORY_PATH: str = f"{get_data_path()}/memory/chat_memory.json"
CORE_MEMORY_PATH: str = f"{get_data_path()}/memory/core.txt"


class SessionManager:

    def __init__(
        self,
        db: DatabaseService,
        kira_config: KiraConfig,
        event_bus: Optional[EventBus] = None,
    ):
        self.db = db
        self.kira_config = kira_config
        self.event_bus = event_bus
        self.max_memory_length = int(kira_config["bot_config"].get("bot").get("max_memory_length"))
        self.chat_memory_path = CHAT_MEMORY_PATH

        self.memory_lock = Lock()
        self._background_tasks: set[asyncio.Task] = set()

        # === Session history ===
        self.chat_memory = self._load_memory(self.chat_memory_path)
        self._ensure_memory_format()

    @staticmethod
    def _load_memory(path: str) -> Dict[str, dict]:
        """加载会话记忆文件"""
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    memory_content = f.read()
                    if memory_content.strip():
                        return json.loads(memory_content)
                    else:
                        return {}
            except Exception as e:
                import traceback
                err = traceback.format_exc()
                logger.error(f"Error loading memory from {path}: {e}")
                logger.error(err)
                return {}
        else:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            return {}

    def _ensure_memory_format(self):
        for session in self.chat_memory:
            session_content = self.chat_memory[session]
            if isinstance(session_content, dict):
                continue

            if isinstance(session_content, list):
                self.chat_memory[session] = {
                    "title": "",
                    "description": "",
                    "timestamp": None,
                    "memory": session_content
                }
        self._save_memory(self.chat_memory, self.chat_memory_path)

    def _ensure_session_data(self, session: str):
        with self.memory_lock:
            if session not in self.chat_memory:
                self.chat_memory[session] = {
                    "title": "",
                    "description": "",
                    "timestamp": None,
                    "memory": []
                }
            else:
                session_data = self.chat_memory[session]
                if "title" not in session_data:
                    session_data["title"] = ""
                if "description" not in session_data:
                    session_data["description"] = ""
                if "timestamp" not in session_data:
                    session_data["timestamp"] = None
            self._save_memory()

    def _save_memory(self, memory: Dict[str, dict] = None, path: str = None) -> bool:
        """保存记忆到文件"""
        if not memory:
            memory = self.chat_memory
        if not path:
            path = self.chat_memory_path
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(json.dumps(memory, indent=4, ensure_ascii=False))
            return True
        except Exception as e:
            logger.error(f"Error saving memory to {path}: {e}")
            return False

    @overload
    def get_session_info(self, session: None = None) -> List[Session]:
        ...

    @overload
    def get_session_info(self, session: str) -> Session:
        ...

    def get_session_info(self, session: Optional[str] = None):
        if session is None:
            session_info_list = []
            for s, si in self.chat_memory.items():
                parts = s.split(":", maxsplit=2)
                session_data = self.chat_memory[s]
                session_info_list.append(Session(
                    adapter_name=parts[0],
                    session_type=parts[1],
                    session_id=parts[2],
                    session_title=session_data.get("title"),
                    session_description=session_data.get("description"),
                    timestamp=session_data.get("timestamp")
                ))
            return session_info_list

        parts = session.split(":", maxsplit=2)

        self._ensure_session_data(session)
        session_data = self.chat_memory[session]
        return Session(
            adapter_name=parts[0],
            session_type=parts[1],
            session_id=parts[2],
            session_title=session_data.get("title"),
            session_description=session_data.get("description"),
            timestamp=session_data.get("timestamp")
        )

    def update_session_info(self, session: str, title: str = None, description: str = None):
        self._ensure_session_data(session)
        with self.memory_lock:
            session_data = self.chat_memory[session]
            if title:
                session_data["title"] = title
            if description:
                session_data["description"] = description
            self._save_memory()

    def get_memory_count(self, session: str) -> int:
        if session not in self.chat_memory:
            return 0
        return len(self.chat_memory[session].get("memory", []))

    def fetch_memory(self, session: str):
        self._ensure_session_data(session)
        mem_list = self.chat_memory[session].get("memory", [])
        messages = []
        for chunk in mem_list:
            for message in chunk:
                messages.append(message)
        return messages

    def read_memory(self, session: str):
        self._ensure_session_data(session)
        return self.chat_memory[session].get("memory", [])

    def get_existing_memory_snapshot(self, session: str) -> Optional[list[list[dict]]]:
        """Return a copy of existing memory without creating a missing session."""
        with self.memory_lock:
            session_data = self.chat_memory.get(session)
            if session_data is None:
                return None
            return copy.deepcopy(session_data.get("memory", []))

    def write_memory(self, session: str, memory: list[list[dict]]):
        with self.memory_lock:
            old_memory = copy.deepcopy(self.chat_memory[session].get("memory", []))
            self.chat_memory[session]["memory"] = memory
            saved = self._save_memory(self.chat_memory, self.chat_memory_path)
            new_memory = copy.deepcopy(memory)
        if saved:
            self._publish_session_event(
                "session_memory_written",
                {
                    "session": session,
                    "old_memory": old_memory,
                    "new_memory": new_memory,
                },
            )
        logger.info(f"Memory written for {session}")

    def update_memory(self, session: str, new_chunk):
        self._ensure_session_data(session)
        from core.agent.message import OpenAIMessage
        new_chunk = [m.to_dict() if isinstance(m, OpenAIMessage) else m for m in new_chunk]
        with self.memory_lock:
            session_data = self.chat_memory[session]

            session_data["timestamp"] = int(time.time())
            session_data["memory"].append(new_chunk)
            if len(session_data["memory"]) > self.max_memory_length:
                session_data["memory"] = session_data["memory"][-self.max_memory_length:]
            saved = self._save_memory(self.chat_memory, self.chat_memory_path)
            published_chunk = copy.deepcopy(new_chunk)
        if saved:
            self._publish_session_event(
                "session_memory_updated",
                {"session": session, "new_chunk": published_chunk},
            )
        logger.info(f"Memory updated for {session}")

    def _publish_session_event(self, event_type: str, payload: dict) -> None:
        """Queue a session lifecycle event after its state has been persisted."""
        if not getattr(self, "event_bus", None):
            return
        from core.event_bus import SystemEvent

        publish_coro = self.event_bus.publish(
            SystemEvent(event_type=event_type, payload=payload, source="session_manager")
        )
        try:
            task = asyncio.create_task(
                publish_coro,
                name=f"{event_type}_event",
            )
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
        except RuntimeError:
            publish_coro.close()
            logger.warning("Unable to publish session lifecycle event outside a running event loop")

    def delete_session(self, session: str):
        deleted = False
        with self.memory_lock:
            deleted = session in self.chat_memory
            old_memory = copy.deepcopy(
                self.chat_memory.get(session, {}).get("memory", [])
            )
            self.chat_memory.pop(session, None)
            saved = self._save_memory(self.chat_memory, self.chat_memory_path)
        if deleted and saved:
            self._publish_session_event(
                "session_deleted",
                {"session": session, "old_memory": old_memory},
            )
        logger.info(f"Memory deleted for {session}")
