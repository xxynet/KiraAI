import asyncio
import json
import os
from typing import Dict, List
from threading import Lock
from core.logging_manager import get_logger

logger = get_logger("memory_manager", "green")


class MemoryManager:
    """管理聊天记忆的读写操作"""
    
    def __init__(self,
                 kira_config,
                 chat_memory_path: str = "data/memory/chat_memory.json",
                 core_memory_path: str = "data/memory/core.txt"):
        self.kira_config = kira_config
        self.max_memory_length = int(kira_config["bot_config"].get("bot").get("max_memory_length"))
        self.chat_memory_path = chat_memory_path
        self.core_memory_path = core_memory_path

        self.memory_lock = Lock()
        
        # 初始化记忆数据
        self.chat_memory = self._load_memory(self.chat_memory_path)
        
        logger.info("MemoryManager initialized")

    @staticmethod
    def _load_memory(path: str) -> Dict[str, List]:
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
            # 确保目录存在
            os.makedirs(os.path.dirname(path), exist_ok=True)
            return {}
    
    def _save_memory(self, memory: Dict[str, List], path: str):
        """保存记忆到文件"""
        try:
            with self.memory_lock:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(json.dumps(memory, indent=4, ensure_ascii=False))
        except Exception as e:
            logger.error(f"Error saving memory to {path}: {e}")

    def fetch_memory(self, session: str):
        if session not in self.chat_memory:
            self.chat_memory[session] = []
            return []
        else:
            mem_list = self.chat_memory[session]
            messages = []
            for chunk in mem_list:
                for message in chunk:
                    messages.append(message)
            return messages

    def update_memory(self, session: str, new_chunk):
        self.chat_memory[session].append(new_chunk)
        if len(self.chat_memory[session]) > self.max_memory_length:
            self.chat_memory[session] = self.chat_memory[session][1:]
        self._save_memory(self.chat_memory, self.chat_memory_path)
        logger.info(f"Memory updated for {session}")

    def get_core_memory(self):
        os.makedirs(os.path.dirname(self.core_memory_path), exist_ok=True)
        with open(self.core_memory_path, "r", encoding='utf-8') as mem:
            lines = mem.readlines()
        memory_str = ""
        for i, line in enumerate(lines):
            memory_str += f"[{i}] {line}"
        return memory_str
