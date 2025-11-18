import os
from utils.tool_utils import BaseTool


CORE_MEMORY_PATH = "data/memory/core.txt"


def _ensure_memory_file() -> None:
    os.makedirs(os.path.dirname(CORE_MEMORY_PATH), exist_ok=True)
    if not os.path.exists(CORE_MEMORY_PATH):
        with open(CORE_MEMORY_PATH, "w", encoding="utf-8") as _:
            _.write("")


class MemoryAddTool(BaseTool):
    name = "memory_add"
    description = "添加一条记忆"
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "要记录的记忆文本"}
        },
        "required": ["text"]
    }

    async def execute(self, text: str) -> str:
        _ensure_memory_file()
        with open(CORE_MEMORY_PATH, "r", encoding="utf-8") as mem:
            mem_str = mem.read()
        with open(CORE_MEMORY_PATH, "a", encoding="utf-8") as mem:
            if mem_str and not mem_str.endswith("\n"):
                mem.write("\n")
            mem.write(text + "\n")
        return "Core memory added"


class MemoryUpdateTool(BaseTool):
    name = "memory_update"
    description = "修改特定记忆"
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
    description = "删除一条记忆"
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
