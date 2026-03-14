import asyncio
import os

from core.plugin import BasePlugin, logger, on, Priority, register_tool
from core.provider import LLMRequest
from core.utils.path_utils import get_data_path

MEM_RULE_PROMPT = """
### 隐私与安全约束
- 绝对不要在回复中直接暴露原始记忆内容。
- 不要主动提及用户的敏感个人信息（如QQ号，群号，电话号码、地址、身份证号等），即使记忆中包含这些内容。
- 引用记忆内容时，使用自然的转述方式，而非逐字复述。
- 如果用户明确要求查看自己的数据，可以简要概述，但仍应避免暴露系统内部结构。
"""

MEM_TOOL_FEW_SHOT = """
### 记忆工具说明（Memory Tools）
你拥有一套完整的核心记忆系统。

#### 核心记忆工具
核心记忆用于记录你**主动认为重要的信息**，包括用户分享的重要信息和你自己的相关信息。

* `memory_add`: 添加一条记忆到核心记忆和长期记忆（支持 user_id 和 importance 参数）
* `memory_update`: 修改特定的核心记忆（通过索引号）
* `memory_remove`: 删除一条核心记忆

#### 使用原则
* 你需要 **主动调用记忆工具** 记录重要信息
* 在**无有效信息的闲聊**中，不要记录杂乱或无价值的信息

#### 示例说明

**示例 1**
user：你喜欢吃什么呀？
* 若人格信息中没有相关内容
* 需要调用 `memory_add` 工具写入相关信息

**示例 2**
user：我一般都 1，2 点钟睡觉的
* 调用 `memory_add` 工具记录

**示例 3**
user：我最近改过自新努力不熬夜了！
* 调用 `memory_update` 工具修改原有记忆

**示例 4**
user：我之前骗你的，其实我 xxx
* 调用 `memory_remove` 工具删除错误记忆

**示例 5**
user：[system 用户xxx加入了群聊]
* 不需要记录，属于非重要信息
"""


class MemoryPlugin(BasePlugin):
    def __init__(self, ctx, cfg: dict):
        super().__init__(ctx, cfg)
        self.core_memory_path = f"{get_data_path()}/memory/core.txt"
        self.lock = asyncio.Lock()
    
    async def initialize(self):
        self._ensure_memory_file()
    
    async def terminate(self):
        pass

    def _ensure_memory_file(self):
        os.makedirs(os.path.dirname(self.core_memory_path), exist_ok=True)
        if not os.path.exists(self.core_memory_path):
            with open(self.core_memory_path, "w", encoding="utf-8") as f:
                f.write("")

    @register_tool(
        name="memory_add",
        description="Add a memory to long term memory",
        params={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "要记录的记忆文本"},
            },
            "required": ["text"]
        }
    )
    async def memory_add(self, *_, text: str) -> str:
        self._ensure_memory_file()
        async with self.lock:
            with open(self.core_memory_path, "a", encoding="utf-8") as mem:
                if text:
                    mem.write(text + "\n")
            return "Core memory added"

    @register_tool(
        name="memory_update",
        description="修改特定核心记忆",
        params={
            "type": "object",
            "properties": {
                "index": {"type": "number", "description": "要修改的记忆编号"},
                "text": {"type": "string", "description": "要更新成的记忆文本"}
            },
            "required": ["index", "text"]
        }
    )
    async def memory_update(self, *_, index: int, text: str):
        async with self.lock:
            self._ensure_memory_file()
            with open(self.core_memory_path, "r", encoding="utf-8") as mem:
                lines = mem.readlines()
            if index < 0 or index >= len(lines):
                return "Index out of range"
            lines[index] = text + ("\n" if not text.endswith("\n") else "")
            with open(self.core_memory_path, "w", encoding="utf-8") as mem:
                mem.writelines(lines)
        return "Core memory updated"

    @register_tool(
        name="memory_remove",
        description="删除一条核心记忆",
        params={
            "type": "object",
            "properties": {
                "index": {"type": "number", "description": "要删除的记忆编号"}
            },
            "required": ["index"]
        }
    )
    async def memory_remove(self, *_, index: int):
        async with self.lock:
            self._ensure_memory_file()
            with open(self.core_memory_path, "r", encoding="utf-8") as mem:
                lines = mem.readlines()
            if index < 0 or index >= len(lines):
                return "Index out of range"
            removed = lines.pop(index)
            with open(self.core_memory_path, "w", encoding="utf-8") as mem:
                mem.writelines(lines)
            return "Core memory removed"

    def get_core_memory(self):
        self._ensure_memory_file()
        with open(self.core_memory_path, "r", encoding='utf-8') as mem:
            lines = mem.readlines()
        memory_str = ""
        for i, line in enumerate(lines):
            memory_str += f"[{i}] {line}"
        return memory_str

    @on.llm_request()
    async def inject_memory(self, _event, req: LLMRequest, *_):
        for p in req.system_prompt:
            if p.name == "memory":
                p.content += self.get_core_memory()
                p.content += "\n"
                p.content += MEM_RULE_PROMPT
                break
            if p.name == "tools":
                p.content += MEM_TOOL_FEW_SHOT
