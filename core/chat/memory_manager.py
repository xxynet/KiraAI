import asyncio
import json
import os
from typing import Dict, List
from threading import Lock
from core.logging_manager import get_logger

from core.config import KiraConfig

from .session import Session

logger = get_logger("memory_manager", "green")

CHAT_MEMORY_PATH: str = "data/memory/chat_memory.json"
CORE_MEMORY_PATH: str = "data/memory/core.txt"


class MemoryManager:
    """管理聊天记忆的读写操作"""
    
    def __init__(self, kira_config: KiraConfig):
        self.kira_config = kira_config
        self.max_memory_length = int(kira_config["bot_config"].get("bot").get("max_memory_length"))
        self.chat_memory_path = CHAT_MEMORY_PATH
        self.core_memory_path = CORE_MEMORY_PATH

        self.memory_lock = Lock()
        
        # init memory data
        self.chat_memory = self._load_memory(self.chat_memory_path)
        self._ensure_memory_format()
        
        logger.info("MemoryManager initialized")

    @staticmethod
    def _load_memory(path: str) -> Dict[str, dict]:
        """加载记忆文件"""
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
            # make sure the directory exists
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
                    "memory": session_content
                }
        self._save_memory(self.chat_memory, self.chat_memory_path)
    
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
        parts = session.split(":")
        if not len(parts) == 3:
            raise ValueError("Invalid session ID")
        if session not in self.chat_memory:
            self.chat_memory[session] = {
                "title": "",
                "description": "",
                "memory": []
            }
        return Session(
            adapter_name=parts[0],
            session_type=parts[1],
            session_id=parts[2],
            session_title=self.chat_memory[session]["title"],
            session_description=self.chat_memory[session]["description"]
        )

    def update_session_info(self, session: str, title: str = None, description: str = None):
        with self.memory_lock:
            if session not in self.chat_memory:
                self.chat_memory[session] = {
                    "title": "",
                    "description": "",
                    "memory": []
                }
            if title:
                self.chat_memory[session]["title"] = title
            if description:
                self.chat_memory[session]["description"] = description
            self._save_memory()

    def get_memory_count(self, session: str) -> int:
        if session not in self.chat_memory:
            return 0
        return len(self.chat_memory[session].get("memory", []))

    def fetch_memory(self, session: str):
        if session not in self.chat_memory:
            self.chat_memory[session] = {
                "title": "",
                "description": "",
                "memory": []
            }
            return []
        else:
            mem_list = self.chat_memory[session].get("memory", [])
            messages = []
            for chunk in mem_list:
                for message in chunk:
                    messages.append(message)
            return messages

    def read_memory(self, session: str):
        if session not in self.chat_memory:
            self.chat_memory[session] = {
                "title": "",
                "description": "",
                "memory": []
            }
            return []
        else:
            return self.chat_memory[session].get("memory", [])

    def write_memory(self, session: str, memory: list[list[dict]]):
        with self.memory_lock:
            self.chat_memory[session]["memory"] = memory
            self._save_memory(self.chat_memory, self.chat_memory_path)
        logger.info(f"Memory written for {session}")

    def update_memory(self, session: str, new_chunk):
        with self.memory_lock:
            self.chat_memory[session]["memory"].append(new_chunk)
            if len(self.chat_memory[session]["memory"]) > self.max_memory_length:
                self.chat_memory[session]["memory"] = self.chat_memory[session]["memory"][1:]
            self._save_memory(self.chat_memory, self.chat_memory_path)
        logger.info(f"Memory updated for {session}")

    def delete_session(self, session: str):
        with self.memory_lock:
            self.chat_memory.pop(session)
            self._save_memory(self.chat_memory, self.chat_memory_path)
        logger.info(f"Memory deleted for {session}")

    def get_core_memory(self):
        os.makedirs(os.path.dirname(self.core_memory_path), exist_ok=True)
        with open(self.core_memory_path, "r", encoding='utf-8') as mem:
            lines = mem.readlines()
        memory_str = ""
        for i, line in enumerate(lines):
            memory_str += f"[{i}] {line}"
        return memory_str
