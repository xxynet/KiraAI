"""
KiraOS Plugin — Combines two OS-level capabilities:

  1. **User Memory (SQLite)**: Per-user profile & event persistence.
     Tools: save_user_profile, save_user_event, remove_user_profile
     Hook:  Auto-inject memory context into system prompt before LLM calls.

  2. **Skill Router (Progressive Disclosure)**:
     Scans `data/skills/` for skill folders each containing:
       - manifest.json   — lightweight tool definition (always loaded)
       - instruction.md  — detailed execution rules (loaded on-demand)
     When the LLM triggers a skill, instruction.md is loaded and returned
     as the tool result — the main LLM reads and follows the instructions
     within the SAME tool-loop turn. No extra LLM API call needed.

This mirrors Claude's Skill system: manifests are the "menu",
instructions are "just-in-time loaded programs".
"""

import json
import os
from pathlib import Path
from typing import Optional

from core.plugin import BasePlugin, logger, on, Priority, register_tool
from core.provider import LLMRequest
from core.chat.message_utils import KiraMessageBatchEvent
from core.utils.path_utils import get_data_path

from .db import UserMemoryDB
from .skill_router import SkillRouter, SkillInfo

# ════════════════════════════════════════════════════════════════════
#  Prompt Fragments
# ════════════════════════════════════════════════════════════════════

MEM_RULE_PROMPT = """\
### 用户记忆系统使用规范
你拥有一套基于数据库的 **用户记忆系统**，可以为每位用户独立存储画像信息和事件日志。

#### 隐私与安全约束
- 绝对不要在回复中直接暴露原始记忆内容或数据库结构。
- 不要主动提及用户的敏感个人信息（如电话号码、地址、身份证号等），即使记忆中包含。
- 引用记忆内容时，使用自然的转述方式，而非逐字复述。
- 自然地体现出你记得用户的信息，而不是宣告"我从记忆中查到..."。
"""

MEM_TOOL_FEW_SHOT = """\
### 用户记忆工具说明（User Memory Tools）

#### 工具列表
* `save_user_profile`: 保存或更新用户的画像信息（键值对形式，如 "生日": "1月1日"）
* `save_user_event`: 记录用户相关的事件日志（如 "用户通过了考试"）
* `remove_user_profile`: 删除用户的某条画像信息

#### 使用原则
* 当用户分享关于自己的重要信息时（偏好、身份、习惯等），主动调用 `save_user_profile` 记录
* 当发生值得记住的事件时，调用 `save_user_event` 记录
* 当用户纠正之前的信息时，使用 `save_user_profile` 覆盖旧值，或用 `remove_user_profile` 删除错误记录
* 在无有效信息的闲聊中，不要记录杂乱或无价值的信息
* user_id 是自动识别的，不需要用户手动提供

#### 画像（profile）与事件（event）的区别
* **画像**：长期稳定的属性信息（姓名、生日、偏好、职业…）→ `save_user_profile`
* **事件**：一次性发生的事情（考试通过、去了某地、生病了…）→ `save_user_event`

#### 示例

**示例 1** — 记录用户画像
user：我叫小明，在北京上大学
→ 调用 `save_user_profile`（key="昵称", value="小明"）
→ 调用 `save_user_profile`（key="所在城市", value="北京"）
→ 调用 `save_user_profile`（key="身份", value="大学生"）

**示例 2** — 记录事件
user：我今天终于跑完了半马！
→ 调用 `save_user_event`（event_summary="完成了半程马拉松"）

**示例 3** — 更新画像
user：我最近搬到上海了
→ 调用 `save_user_profile`（key="所在城市", value="上海"）# 自动覆盖旧值

**示例 4** — 删除错误信息
user：我之前说错了，其实我不养猫
→ 调用 `remove_user_profile`（key="宠物"）
"""

SKILL_FEW_SHOT_HEADER = """\
### 技能工具说明（Skill Tools）
以下工具是通过技能系统动态加载的。当用户的需求匹配某个技能的描述时，调用对应工具。
调用后你会收到该技能的详细执行指令，请严格按照指令内容执行并直接输出结果。

"""


# ════════════════════════════════════════════════════════════════════
#  Plugin Class
# ════════════════════════════════════════════════════════════════════

class UserMemoryPlugin(BasePlugin):
    """
    KiraOS Plugin — Memory + Skill Router.

    Memory: SQLite-backed per-user profile & event storage with auto-injection.
    Skills: Progressive disclosure — manifests loaded at startup, instructions
            loaded on-demand as tool results (zero extra LLM calls).
    """

    def __init__(self, ctx, cfg: dict):
        super().__init__(ctx, cfg)

        # ── Memory config ───────────────────────────────────────────
        db_dir = get_data_path() / "memory"
        self.db_path = str(db_dir / "kiraos.db")
        self.db: UserMemoryDB | None = None
        self.max_events = int(cfg.get("max_events_per_user", 10))
        self.max_profiles = int(cfg.get("max_profiles_per_user", 50))
        self.max_event_keep = int(cfg.get("max_event_keep", 100))

        # ── Skill Router config ─────────────────────────────────────
        skills_dir = cfg.get("skills_dir", "") or str(get_data_path() / "skills")
        self.skill_router = SkillRouter(skills_dir)
        self._registered_skill_names: list[str] = []

    # ════════════════════════════════════════════════════════════════
    #  Lifecycle
    # ════════════════════════════════════════════════════════════════

    async def initialize(self):
        # ── Init memory DB ──────────────────────────────────────────
        self.db = UserMemoryDB(self.db_path)
        logger.info("User memory database ready")

        # ── Discover & register skills ──────────────────────────────
        skills = self.skill_router.discover()
        for skill in skills:
            self._register_skill_tool(skill)

        if skills:
            logger.info(f"Registered {len(skills)} skill(s): {[s.name for s in skills]}")
        else:
            logger.info("No skills found (place skill folders in data/skills/)")

        logger.info("KiraOS plugin initialized (memory + skill router)")

    async def terminate(self):
        # ── Unregister skill tools ──────────────────────────────────
        for name in self._registered_skill_names:
            try:
                self.ctx.llm_api.unregister_tool(name)
            except Exception:
                pass
        self._registered_skill_names.clear()

        self.db = None
        logger.info("KiraOS plugin terminated")

    # ════════════════════════════════════════════════════════════════
    #  Skill Router — dynamic tool registration & instruction injection
    # ════════════════════════════════════════════════════════════════

    def _register_skill_tool(self, skill: SkillInfo):
        """Dynamically register a skill as an LLM tool via ctx.llm_api."""

        async def _skill_executor(event: KiraMessageBatchEvent, **kwargs) -> str:
            return self._execute_skill(skill, event, **kwargs)

        self.ctx.llm_api.register_tool(
            name=skill.name,
            description=skill.description,
            parameters=skill.parameters,
            func=_skill_executor,
        )
        self._registered_skill_names.append(skill.name)

    def _execute_skill(self, skill: SkillInfo, event: KiraMessageBatchEvent, **kwargs) -> str:
        """
        Execute a skill via instruction injection (zero extra LLM calls):
          1. Load instruction.md with argument substitution
          2. Optionally append user memory context
          3. Return the instruction as tool_result — the main LLM reads it
             in the same tool-loop turn and follows the instructions directly

        This mirrors Claude's Skill pattern: the skill's full instruction
        is injected just-in-time as the tool's return value, so the main
        LLM "learns" the skill on the fly without a separate API call.
        """
        logger.info(f"Loading skill '{skill.name}' instruction (args: {kwargs})")

        # Build instruction from template with argument substitution
        instruction = self.skill_router.build_instruction_prompt(skill, kwargs)
        if not instruction:
            return f"Error: skill '{skill.name}' has empty instruction"

        # Assemble the tool result that the main LLM will see
        parts = []
        parts.append(f"<skill name=\"{skill.name}\">")
        parts.append(instruction)

        # Optionally include user memory for context-aware skill execution
        user_id = self._get_primary_user_id(event)
        if self.db and user_id != "unknown":
            mem_ctx = self.db.build_user_context(user_id, max_events=3)
            if mem_ctx:
                parts.append(f"\n<context>\n{mem_ctx}\n</context>")

        parts.append("</skill>")
        parts.append("请严格按照上述技能指令执行，直接输出执行结果。")

        return "\n".join(parts)

    # ════════════════════════════════════════════════════════════════
    #  Memory — helpers
    # ════════════════════════════════════════════════════════════════

    @staticmethod
    def _extract_user_ids(event: KiraMessageBatchEvent) -> list[str]:
        """Extract unique sender user_ids from the batch event."""
        seen = set()
        user_ids = []
        for msg in event.messages:
            if msg.sender and msg.sender.user_id:
                uid = msg.sender.user_id
                if uid not in seen and uid != "unknown":
                    seen.add(uid)
                    user_ids.append(uid)
        return user_ids

    @staticmethod
    def _get_primary_user_id(event: KiraMessageBatchEvent) -> str:
        """Get the user_id of the last message sender (primary user)."""
        if event.messages:
            last_msg = event.messages[-1]
            if last_msg.sender and last_msg.sender.user_id:
                return last_msg.sender.user_id
        return "unknown"

    # ════════════════════════════════════════════════════════════════
    #  Memory — Tools
    # ════════════════════════════════════════════════════════════════

    @register_tool(
        name="save_user_profile",
        description="保存或更新用户的画像信息（长期稳定的属性，如昵称、偏好、身份等）。相同 key 会覆盖旧值。",
        params={
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "画像键名，如 '昵称'、'生日'、'所在城市'、'职业' 等"
                },
                "value": {
                    "type": "string",
                    "description": "画像值"
                },
                "user_id": {
                    "type": "string",
                    "description": "目标用户ID，留空则默认为当前消息发送者"
                }
            },
            "required": ["key", "value"]
        }
    )
    async def save_user_profile(self, event: KiraMessageBatchEvent, key: str, value: str, user_id: str = "") -> str:
        if not self.db:
            return "Error: memory database not initialized"
        if not user_id:
            user_id = self._get_primary_user_id(event)
        if user_id == "unknown":
            return "Error: cannot determine user_id"

        # Check profile count limit
        count = self.db.get_profile_count(user_id)
        if count >= self.max_profiles:
            return f"Error: user profile limit reached ({self.max_profiles}). Remove old entries before adding new ones."

        self.db.save_profile(user_id, key, value)
        logger.info(f"Saved profile for user {user_id}: {key}={value}")
        return f"已保存用户 {user_id} 的画像信息: {key} = {value}"

    @register_tool(
        name="save_user_event",
        description="记录用户相关的事件日志（一次性发生的事件，如完成某件事、去了某地等）",
        params={
            "type": "object",
            "properties": {
                "event_summary": {
                    "type": "string",
                    "description": "事件简要描述"
                },
                "user_id": {
                    "type": "string",
                    "description": "目标用户ID，留空则默认为当前消息发送者"
                }
            },
            "required": ["event_summary"]
        }
    )
    async def save_user_event(self, event: KiraMessageBatchEvent, event_summary: str, user_id: str = "") -> str:
        if not self.db:
            return "Error: memory database not initialized"
        if not user_id:
            user_id = self._get_primary_user_id(event)
        if user_id == "unknown":
            return "Error: cannot determine user_id"

        self.db.save_event(user_id, event_summary)

        # Auto-cleanup old events
        cleaned = self.db.cleanup_old_events(user_id, keep=self.max_event_keep)
        if cleaned > 0:
            logger.info(f"Cleaned up {cleaned} old events for user {user_id}")

        logger.info(f"Saved event for user {user_id}: {event_summary}")
        return f"已记录用户 {user_id} 的事件: {event_summary}"

    @register_tool(
        name="remove_user_profile",
        description="删除用户的某条画像信息",
        params={
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "要删除的画像键名"
                },
                "user_id": {
                    "type": "string",
                    "description": "目标用户ID，留空则默认为当前消息发送者"
                }
            },
            "required": ["key"]
        }
    )
    async def remove_user_profile(self, event: KiraMessageBatchEvent, key: str, user_id: str = "") -> str:
        if not self.db:
            return "Error: memory database not initialized"
        if not user_id:
            user_id = self._get_primary_user_id(event)
        if user_id == "unknown":
            return "Error: cannot determine user_id"

        removed = self.db.remove_profile(user_id, key)
        if removed:
            logger.info(f"Removed profile key '{key}' for user {user_id}")
            return f"已删除用户 {user_id} 的画像信息: {key}"
        else:
            return f"未找到用户 {user_id} 的画像 '{key}'，无需删除"

    # ════════════════════════════════════════════════════════════════
    #  LLM Hook — inject memory context + skill manifest descriptions
    # ════════════════════════════════════════════════════════════════

    @on.llm_request()
    async def inject_context(self, event: KiraMessageBatchEvent, req: LLMRequest):
        """
        Before each LLM call:
          1. Inject per-user memory context into the system prompt
          2. Inject skill tool descriptions (few-shot) so LLM knows about skills
        """
        # ── Part 1: Memory injection ────────────────────────────────
        memory_context = ""
        if self.db:
            user_ids = self._extract_user_ids(event)
            if user_ids:
                memory_blocks = []
                for uid in user_ids:
                    ctx_str = self.db.build_user_context(uid, max_events=self.max_events)
                    if ctx_str:
                        memory_blocks.append(ctx_str)
                if memory_blocks:
                    memory_context = "\n".join(memory_blocks)

        # ── Part 2: Skill manifest descriptions ─────────────────────
        skill_few_shot = ""
        if self._registered_skill_names:
            skill_lines = [SKILL_FEW_SHOT_HEADER]
            for skill_name in self._registered_skill_names:
                skill = self.skill_router.get_skill(skill_name)
                if skill:
                    skill_lines.append(f"* `{skill.name}`: {skill.description}")
            skill_few_shot = "\n".join(skill_lines) + "\n"

        # ── Inject into prompt sections ─────────────────────────────
        injected_memory = False
        for p in req.system_prompt:
            if p.name == "memory":
                if memory_context:
                    p.content += f"\n{memory_context}\n"
                    p.content += MEM_RULE_PROMPT
                    injected_memory = True
            if p.name == "tools":
                p.content += MEM_TOOL_FEW_SHOT
                if skill_few_shot:
                    p.content += skill_few_shot

        # Fallback: if no "memory" section found but we have memory context
        if not injected_memory and memory_context and req.system_prompt:
            req.system_prompt[-1].content += f"\n{memory_context}\n{MEM_RULE_PROMPT}"
