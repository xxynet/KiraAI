import asyncio
import json
import os
import time
from typing import Optional
from core.utils.tool_utils import BaseTool
from core.logging_manager import get_logger

logger = get_logger("memory_tools", "green")


CORE_MEMORY_PATH = "data/memory/core.txt"
CORE_VECTOR_MAP_PATH = "data/memory/core_vector_map.json"

# 保护核心记忆文件和向量映射的并发访问
MEMORY_IO_LOCK = asyncio.Lock()

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


def _load_vector_map() -> dict[int, str]:
    """加载核心记忆行号 → 向量 ID 映射"""
    if os.path.exists(CORE_VECTOR_MAP_PATH):
        try:
            with open(CORE_VECTOR_MAP_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            # JSON keys are strings, convert back to int
            return {int(k): v for k, v in data.items()}
        except Exception as e:
            logger.warning(f"Failed to load vector map from {CORE_VECTOR_MAP_PATH}: {e}")
    return {}


def _save_vector_map(mapping: dict[int, str]) -> None:
    """保存核心记忆行号 → 向量 ID 映射"""
    try:
        os.makedirs(os.path.dirname(CORE_VECTOR_MAP_PATH), exist_ok=True)
        with open(CORE_VECTOR_MAP_PATH, "w", encoding="utf-8") as f:
            json.dump(mapping, f, indent=2)
    except Exception as e:
        logger.warning(f"Failed to save vector map: {e}")
        raise


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
        # Sanitize importance: coerce to int and clamp to 1-10
        try:
            importance = int(importance)
        except (TypeError, ValueError):
            importance = 5
        importance = min(max(importance, 1), 10)

        # 在锁外生成 embedding（可能耗时较长）
        embedding = None
        entry = None
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
            if hasattr(_memory_manager, '_llm_client') and _memory_manager._llm_client:
                try:
                    embeddings = await _memory_manager._llm_client.embed([text])
                    if embeddings and embeddings[0]:
                        embedding = embeddings[0]
                except Exception as e:
                    logger.debug(f"Failed to generate embedding for memory (text length={len(text)}): {e}")

        async with MEMORY_IO_LOCK:
            # 写入核心记忆文件（保持向后兼容）
            _ensure_memory_file()
            with open(CORE_MEMORY_PATH, "r", encoding="utf-8") as mem:
                mem_str = mem.read()
            # 计算新行的索引（写入前的行数）
            line_index = len(mem_str.splitlines())
            with open(CORE_MEMORY_PATH, "a", encoding="utf-8") as mem:
                if mem_str and not mem_str.endswith("\n"):
                    mem.write("\n")
                mem.write(text + "\n")

            # 同时写入向量长期记忆
            if entry is not None:
                try:
                    await asyncio.to_thread(_memory_manager.vector_store.add_memory, entry, embedding=embedding)
                except Exception as e:
                    logger.warning(f"Could not store memory to vector DB (entry.id={entry.id}): {e}")
                    return f"Core memory added, but vector store write failed: {e}"

                try:
                    vmap = _load_vector_map()
                    vmap[line_index] = entry.id
                    _save_vector_map(vmap)
                except Exception as e:
                    logger.warning(f"Core memory added and vector stored, but vector map persistence failed (entry.id={entry.id}): {e}")
                    return f"Core memory added, but vector map save failed: {e}"
            else:
                logger.warning("memory_manager not available, long-term memory not written")
                return "Core memory added; long-term memory not available"

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
        try:
            if isinstance(index, float) and not index.is_integer():
                return "Index must be an integer"
            index = int(index)
        except (TypeError, ValueError):
            return "Index must be an integer"

        # 在锁外生成 embedding（可能耗时较长）
        embedding = None
        if _memory_manager and hasattr(_memory_manager, '_llm_client') and _memory_manager._llm_client:
            try:
                embeddings = await _memory_manager._llm_client.embed([text])
                if embeddings and embeddings[0]:
                    embedding = embeddings[0]
            except Exception as e:
                logger.debug(f"Failed to generate embedding for updated memory: {e}")

        async with MEMORY_IO_LOCK:
            _ensure_memory_file()
            with open(CORE_MEMORY_PATH, "r", encoding="utf-8") as mem:
                lines = mem.readlines()
            if index < 0 or index >= len(lines):
                return "Index out of range"
            old_text = lines[index].strip()
            lines[index] = text + ("\n" if not text.endswith("\n") else "")
            with open(CORE_MEMORY_PATH, "w", encoding="utf-8") as mem:
                mem.writelines(lines)

            # 同步更新向量长期记忆中匹配的条目
            vector_sync_error = None
            if _memory_manager and hasattr(_memory_manager, 'vector_store'):
                try:
                    vector_id = None
                    vmap = _load_vector_map()

                    # 优先通过持久化映射查找
                    if index in vmap:
                        candidate = await asyncio.to_thread(_memory_manager.vector_store.get_memory_by_id, vmap[index])
                        if candidate:
                            vector_id = candidate.id
                        else:
                            logger.debug(f"Mapped vector_id {vmap[index]} not found in store, falling back")

                    # 回退：按内容匹配查找
                    if not vector_id and old_text:
                        all_entries = await asyncio.to_thread(_memory_manager.vector_store.get_all_memories)
                        matched = [e for e in all_entries if e.content.strip() == old_text and e.memory_type == "fact"]
                        if matched:
                            vector_id = matched[0].id

                    if vector_id:
                        try:
                            ok = await asyncio.to_thread(_memory_manager.vector_store.update_memory, vector_id, content=text, embedding=embedding)
                            if not ok:
                                vector_sync_error = f"update_memory returned False for entry {vector_id} (embedding={'present' if embedding else 'None'})"
                                logger.warning(vector_sync_error)
                        except Exception as e:
                            vector_sync_error = f"update_memory raised for entry {vector_id}: {e}"
                            logger.error(vector_sync_error)
                    else:
                        vector_sync_error = f"Could not locate vector entry for core memory index {index}"
                        logger.warning(vector_sync_error)
                except Exception as e:
                    vector_sync_error = f"Failed to sync update to vector DB: {e}"
                    logger.warning(vector_sync_error)

        if vector_sync_error:
            return f"Core memory updated, but vector sync failed: {vector_sync_error}"
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
        try:
            if isinstance(index, float) and not index.is_integer():
                return "Index must be an integer"
            index = int(index)
        except (TypeError, ValueError):
            return "Index must be an integer"
        async with MEMORY_IO_LOCK:
            _ensure_memory_file()
            with open(CORE_MEMORY_PATH, "r", encoding="utf-8") as mem:
                lines = mem.readlines()
            if index < 0 or index >= len(lines):
                return "Index out of range"
            removed = lines.pop(index)
            with open(CORE_MEMORY_PATH, "w", encoding="utf-8") as mem:
                mem.writelines(lines)

            # 同步删除向量长期记忆中匹配的条目
            removed_text = removed.strip()
            vector_sync_error = None
            vmap = None
            try:
                vmap = _load_vector_map()
            except Exception as e:
                map_load_error = f"Failed to load vector map before deletion: {e}"
                logger.warning(map_load_error)
                vector_sync_error = map_load_error
            if removed_text and _memory_manager and hasattr(_memory_manager, 'vector_store'):
                try:
                    vector_id = None

                    # 优先通过持久化映射查找
                    if vmap and index in vmap:
                        candidate = await asyncio.to_thread(_memory_manager.vector_store.get_memory_by_id, vmap[index])
                        if candidate:
                            vector_id = candidate.id

                    # 回退：按内容匹配查找
                    if not vector_id:
                        all_entries = await asyncio.to_thread(_memory_manager.vector_store.get_all_memories)
                        matched = [e for e in all_entries if e.content.strip() == removed_text and e.memory_type == "fact"]
                        if matched:
                            vector_id = matched[0].id

                    if vector_id:
                        delete_ok = await asyncio.to_thread(_memory_manager.vector_store.delete_memory, vector_id)
                        if not delete_ok:
                            vector_sync_error = f"delete_memory returned False for entry {vector_id}"
                            logger.warning(vector_sync_error)
                except Exception as e:
                    vector_sync_error = f"Failed to sync delete to vector DB: {e}"
                    logger.warning(vector_sync_error)

            # 始终更新映射：文件已删除行，映射必须同步前移（无论向量操作是否执行）
            try:
                if vmap is None:
                    raise RuntimeError("vector map unavailable")
                new_map = {}
                for k, v in vmap.items():
                    if k < index:
                        new_map[k] = v
                    elif k > index:
                        new_map[k - 1] = v
                    # k == index 已删除，跳过
                _save_vector_map(new_map)
            except Exception as e:
                map_error = f"Failed to update vector map after deletion: {e}"
                logger.warning(map_error)
                if vector_sync_error:
                    vector_sync_error += f"; {map_error}"
                else:
                    vector_sync_error = map_error

        if vector_sync_error:
            return f"Core memory removed: {removed_text} (vector sync failed: {vector_sync_error})"
        return f"Core memory removed: {removed_text}"


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

    async def execute(self, query: str, user_id: Optional[str] = None, k: int = 5) -> str:
        if not _memory_manager or not hasattr(_memory_manager, 'recall'):
            return "Memory system not available"

        try:
            k = int(k)
        except (TypeError, ValueError):
            return "Error: k must be a positive integer"
        if k <= 0:
            return "Error: k must be a positive integer"

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
            "target": {"type": "string", "description": "关系目标（当 action=set_relationship 时必填）"}
        },
        "required": ["user_id", "action", "value"]
    }

    async def execute(self, user_id: str, action: str, value: str, target: str = "") -> str:
        if not _memory_manager or not hasattr(_memory_manager, 'user_profile_store'):
            return "Profile system not available"

        if not isinstance(action, str) or not action.strip():
            return "action is required"
        action = action.strip()
        allowed_actions = {"add_trait", "remove_trait", "add_fact", "set_name", "set_relationship"}
        if action not in allowed_actions:
            return f"Unknown action: {action}"

        store = _memory_manager.user_profile_store
        if action == "add_trait":
            await asyncio.to_thread(store.add_trait, user_id, value)
            return f"Added trait '{value}' to user {user_id}"
        elif action == "remove_trait":
            await asyncio.to_thread(store.remove_trait, user_id, value)
            return f"Removed trait '{value}' from user {user_id}"
        elif action == "add_fact":
            await asyncio.to_thread(store.add_fact, user_id, value)
            return f"Added fact for user {user_id}"
        elif action == "set_name":
            await asyncio.to_thread(store.update_profile, user_id, name=value)
            return f"Set name '{value}' for user {user_id}"
        elif action == "set_relationship":
            if not target:
                return "target is required for set_relationship"
            await asyncio.to_thread(store.set_relationship, user_id, target, value)
            return f"Set relationship '{value}' with '{target}' for user {user_id}"

        raise RuntimeError("Unreachable action branch in ProfileUpdateTool.execute")
