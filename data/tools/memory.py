import os
import time
from core.utils.tool_utils import BaseTool
from core.logging_manager import get_logger

logger = get_logger("memory_tools", "green")


CORE_MEMORY_PATH = "data/memory/core.txt"

# 全局引用，由 tool_manager 注入
_memory_manager = None


def set_memory_manager(manager):
    """被外部调用以注入 MemoryManager 引用"""
    global _memory_manager
    _memory_manager = manager


def _ensure_memory_file() -> None:
    os.makedirs(os.path.dirname(CORE_MEMORY_PATH), exist_ok=True)
    if not os.path.exists(CORE_MEMORY_PATH):
        with open(CORE_MEMORY_PATH, "w", encoding="utf-8") as _:
            _.write("")


class MemoryAddTool(BaseTool):
    name = "memory_add"
    description = "添加一条记忆到核心记忆和长期记忆"
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "要记录的记忆文本"},
            "user_id": {"type": "string", "description": "相关的用户ID（可选）"},
            "importance": {"type": "number", "description": "重要性评分 1-10（可选，默认5）"}
        },
        "required": ["text"]
    }

    async def execute(self, text: str, user_id: str = "", importance: int = 5) -> str:
        # 写入核心记忆文件（保持向后兼容）
        _ensure_memory_file()
        with open(CORE_MEMORY_PATH, "r", encoding="utf-8") as mem:
            mem_str = mem.read()
        with open(CORE_MEMORY_PATH, "a", encoding="utf-8") as mem:
            if mem_str and not mem_str.endswith("\n"):
                mem.write("\n")
            mem.write(text + "\n")

        # 同时写入向量长期记忆
        if _memory_manager and hasattr(_memory_manager, 'vector_store'):
            from core.chat.vector_store import VectorStore, MemoryEntry
            entry = MemoryEntry(
                id=VectorStore.generate_id(),
                user_id=user_id,
                content=text,
                memory_type="fact",
                importance=importance,
                timestamp=time.time(),
            )

            # 尝试生成 embedding 向量
            embedding = None
            if hasattr(_memory_manager, '_llm_client') and _memory_manager._llm_client:
                try:
                    embeddings = await _memory_manager._llm_client.embed([text])
                    if embeddings and embeddings[0]:
                        embedding = embeddings[0]
                except Exception as e:
                    logger.debug(f"Failed to generate embedding for memory (text length={len(text)}): {e}")

            try:
                _memory_manager.vector_store.add_memory(entry, embedding=embedding)
            except ValueError as e:
                logger.warning(f"Could not store memory to vector DB: {e}")

        return "Core memory added"


class MemoryUpdateTool(BaseTool):
    name = "memory_update"
    description = "修改特定核心记忆"
    parameters = {
        "type": "object",
        "properties": {
            "index": {"type": "number", "description": "要修改的记忆编号"},
            "text": {"type": "string", "description": "要更新成的记忆文本"}
        },
        "required": ["index", "text"]
    }

    async def execute(self, index: int, text: str) -> str:
        _ensure_memory_file()
        with open(CORE_MEMORY_PATH, "r", encoding="utf-8") as mem:
            lines = mem.readlines()
        if index < 0 or index >= len(lines):
            return "Index out of range"
        lines[index] = text + ("\n" if not text.endswith("\n") else "")
        with open(CORE_MEMORY_PATH, "w", encoding="utf-8") as mem:
            mem.writelines(lines)
        return "Core memory updated"


class MemoryRemoveTool(BaseTool):
    name = "memory_remove"
    description = "删除一条核心记忆"
    parameters = {
        "type": "object",
        "properties": {
            "index": {"type": "number", "description": "要删除的记忆编号"}
        },
        "required": ["index"]
    }

    async def execute(self, index: int) -> str:
        _ensure_memory_file()
        with open(CORE_MEMORY_PATH, "r", encoding="utf-8") as mem:
            lines = mem.readlines()
        if index < 0 or index >= len(lines):
            return "Index out of range"
        removed = lines.pop(index)
        with open(CORE_MEMORY_PATH, "w", encoding="utf-8") as mem:
            mem.writelines(lines)
        return f"Core memory removed: {removed.strip()}"


class MemorySearchTool(BaseTool):
    name = "memory_search"
    description = "搜索长期记忆，通过语义相似度检索与查询相关的记忆"
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索查询文本"},
            "user_id": {"type": "string", "description": "要搜索的用户ID（可选）"},
            "k": {"type": "number", "description": "返回结果数量（可选，默认5）"}
        },
        "required": ["query"]
    }

    async def execute(self, query: str, user_id: str = None, k: int = 5) -> str:
        if not _memory_manager or not hasattr(_memory_manager, 'recall'):
            return "Memory system not available"

        memories = await _memory_manager.recall(query, user_id=user_id, k=k)
        if not memories:
            return "No relevant memories found"

        result_lines = []
        for mem in memories:
            type_label = {"fact": "事实", "reflection": "洞察", "summary": "摘要"}.get(mem.memory_type, mem.memory_type)
            result_lines.append(f"[{type_label}] {mem.content}")
        return "\n".join(result_lines)


class ProfileViewTool(BaseTool):
    name = "profile_view"
    description = "查看用户画像信息"
    parameters = {
        "type": "object",
        "properties": {
            "user_id": {"type": "string", "description": "要查看的用户ID"}
        },
        "required": ["user_id"]
    }

    async def execute(self, user_id: str) -> str:
        if not _memory_manager or not hasattr(_memory_manager, 'user_profile_store'):
            return "Profile system not available"

        return _memory_manager.get_user_profile_prompt(user_id)


class ProfileUpdateTool(BaseTool):
    name = "profile_update"
    description = "更新用户画像的特征标签或事实"
    parameters = {
        "type": "object",
        "properties": {
            "user_id": {"type": "string", "description": "用户ID"},
            "action": {"type": "string", "description": "操作类型: add_trait, remove_trait, add_fact, set_name, set_relationship",
                        "enum": ["add_trait", "remove_trait", "add_fact", "set_name", "set_relationship"]},
            "value": {"type": "string", "description": "操作值（特征标签、事实、名字等）"},
            "target": {"type": "string", "description": "关系目标（仅 set_relationship 时使用）"}
        },
        "required": ["user_id", "action", "value"]
    }

    async def execute(self, user_id: str, action: str, value: str, target: str = "") -> str:
        if not _memory_manager or not hasattr(_memory_manager, 'user_profile_store'):
            return "Profile system not available"

        store = _memory_manager.user_profile_store
        if action == "add_trait":
            store.add_trait(user_id, value)
            return f"Added trait '{value}' to user {user_id}"
        elif action == "remove_trait":
            store.remove_trait(user_id, value)
            return f"Removed trait '{value}' from user {user_id}"
        elif action == "add_fact":
            store.add_fact(user_id, value)
            return f"Added fact for user {user_id}"
        elif action == "set_name":
            store.update_profile(user_id, name=value)
            return f"Set name '{value}' for user {user_id}"
        elif action == "set_relationship":
            if not target:
                return "target is required for set_relationship"
            store.set_relationship(user_id, target, value)
            return f"Set relationship '{value}' with '{target}' for user {user_id}"
        else:
            return f"Unknown action: {action}"
