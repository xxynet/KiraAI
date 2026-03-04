import asyncio
import json
import os
import time
import uuid
from typing import Dict, List, Optional
from threading import Lock

from core.logging_manager import get_logger
from core.config import KiraConfig
from core.utils.path_utils import get_data_path

from .session import Session

logger = get_logger("session", "green")

CHAT_MEMORY_PATH: str = f"{get_data_path()}/memory/chat_memory.json"
CORE_MEMORY_PATH: str = f"{get_data_path()}/memory/core.txt"


class SessionManager:

    def __init__(self, kira_config: KiraConfig):
        self.kira_config = kira_config
        self.max_memory_length = int(kira_config["bot_config"].get("bot").get("max_memory_length"))
        self.chat_memory_path = CHAT_MEMORY_PATH

        self.memory_lock = Lock()

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

    def _save_memory(self, memory: Dict[str, dict] = None, path: str = None):
        """保存记忆到文件"""
        if not memory:
            memory = self.chat_memory
        if not path:
            path = self.chat_memory_path
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(json.dumps(memory, indent=4, ensure_ascii=False))
        except Exception as e:
            logger.error(f"Error saving memory to {path}: {e}")

    def get_session_info(self, session: str):
        parts = session.split(":", maxsplit=2)
        if len(parts) != 3:
            raise ValueError("Invalid session ID")
        self._ensure_session_data(session)
        session_data = self.chat_memory[session]
        return Session(
            adapter_name=parts[0],
            session_type=parts[1],
            session_id=parts[2],
            session_title=session_data["title"],
            session_description=session_data["description"],
            timestamp=session_data["timestamp"]
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

    def write_memory(self, session: str, memory: list[list[dict]]):
        with self.memory_lock:
            self.chat_memory[session]["memory"] = memory
            self._save_memory(self.chat_memory, self.chat_memory_path)
        logger.info(f"Memory written for {session}")

    def update_memory(self, session: str, new_chunk):
        self._ensure_session_data(session)
        with self.memory_lock:
            session_data = self.chat_memory[session]

            session_data["timestamp"] = int(time.time())
            session_data["memory"].append(new_chunk)
            if len(session_data["memory"]) > self.max_memory_length:
                session_data["memory"] = session_data["memory"][-self.max_memory_length:]
            self._save_memory(self.chat_memory, self.chat_memory_path)
        logger.info(f"Memory updated for {session}")

    def delete_session(self, session: str):
        with self.memory_lock:
            self.chat_memory.pop(session)
            self._save_memory(self.chat_memory, self.chat_memory_path)
        logger.info(f"Memory deleted for {session}")
