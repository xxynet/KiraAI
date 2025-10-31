import json
import os
from typing import Dict, List
from threading import Lock
from core.logging_manager import get_logger
from core.config_loader import global_config

logger = get_logger("memory_manager", "green")

config_max_memory_length = int(global_config["bot_config"].get("bot").get("max_memory_length"))


class MemoryManager:
    """管理聊天记忆的读写操作"""
    
    def __init__(self, 
                 max_memory_length: int = config_max_memory_length,
                 group_chat_memory_path: str = "data/memory/group_chat_memory.json",
                 private_chat_memory_path: str = "data/memory/chat_memory.json",
                 core_memory_path: str = "data/memory/core.txt"):
        self.max_memory_length = max_memory_length
        self.group_chat_memory_path = group_chat_memory_path
        self.private_chat_memory_path = private_chat_memory_path
        self.core_memory_path = core_memory_path
        
        # 为每个群组创建单独的锁
        self.group_locks: Dict[str, Lock] = {}
        self.memory_lock = Lock()
        
        # 初始化记忆数据
        self.group_chat_memory = self._load_memory(self.group_chat_memory_path)
        self.private_chat_memory = self._load_memory(self.private_chat_memory_path)
        
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
    
    def fetch_group_memory(self, adapter_name: str, group_id: str) -> List[Dict[str, str]]:
        """获取群聊记忆"""
        memory_dict_key = f"{adapter_name}:gm:{group_id}"
        if memory_dict_key not in self.group_chat_memory:
            self.group_chat_memory[memory_dict_key] = []
            return []
        else:
            mem_list = self.group_chat_memory[memory_dict_key]
            messages = []
            for chunk in mem_list:
                for message in chunk:
                    messages.append(message)
            return messages
    
    def update_group_memory(self, adapter_name: str, group_id: str, new_chunk: List[Dict[str, str]]):
        """更新群聊记忆"""
        memory_dict_key = f"{adapter_name}:gm:{group_id}"

        self.group_chat_memory[memory_dict_key].append(new_chunk)
        if len(self.group_chat_memory[memory_dict_key]) > self.max_memory_length:
            self.group_chat_memory[memory_dict_key] = self.group_chat_memory[memory_dict_key][1:]
        self._save_memory(self.group_chat_memory, self.group_chat_memory_path)
        logger.info(f"Group memory updated for {memory_dict_key}")
    
    def fetch_private_memory(self, adapter_name: str, user_id: str) -> List[Dict[str, str]]:
        """获取私聊记忆"""
        memory_dict_key = f"{adapter_name}:dm:{user_id}"

        if memory_dict_key not in self.private_chat_memory:
            self.private_chat_memory[memory_dict_key] = []
            return []
        else:
            mem_list = self.private_chat_memory[memory_dict_key]
            messages = []
            for chunk in mem_list:
                for message in chunk:
                    messages.append(message)
            return messages
    
    def update_private_memory(self, adapter_name: str, user_id: str, new_chunk: List[Dict[str, str]]):
        """更新私聊记忆"""
        memory_dict_key = f"{adapter_name}:dm:{user_id}"

        self.private_chat_memory[memory_dict_key].append(new_chunk)
        if len(self.private_chat_memory[memory_dict_key]) > self.max_memory_length:
            self.private_chat_memory[memory_dict_key] = self.private_chat_memory[memory_dict_key][1:]
        self._save_memory(self.private_chat_memory, self.private_chat_memory_path)
        logger.info(f"Private memory updated for {memory_dict_key}")
    
    def get_group_lock(self, group_id: str) -> Lock:
        """获取群组锁"""
        if group_id not in self.group_locks:
            self.group_locks[group_id] = Lock()
        return self.group_locks[group_id]

    def get_core_memory(self):
        os.makedirs(os.path.dirname(self.core_memory_path), exist_ok=True)
        with open(self.core_memory_path, "r", encoding='utf-8') as mem:
            lines = mem.readlines()
        memory_str = ""
        for i, line in enumerate(lines):
            memory_str += f"[{i}] {line}"
        return memory_str
