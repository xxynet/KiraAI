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

# Prompt injection is now minimal:
# - Memory data only (no usage instructions — those live in tool description)
# - Skill list only when skills exist
# MEM_RULE is a short inline prefix, not a separate block.
SKILL_FEW_SHOT_HEADER = "技能工具（调用后按返回的指令执行）: "


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
            except Exception as e:
                logger.warning(f"Failed to unregister tool '{name}': {e}")
        self._registered_skill_names.clear()

        if self.db:
            self.db.close()
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
        name="memory_update",
        description="批量更新用户记忆。仅在用户分享有价值信息时调用，闲聊不记。示例: 用户说'我叫小明,在北京,今天跑完半马' → [{op:'set',key:'昵称',value:'小明'},{op:'set',key:'城市',value:'北京'},{op:'event',value:'完成半马'}]",
        params={
            "type": "object",
            "properties": {
                "operations": {
                    "type": "array",
                    "description": "操作列表",
                    "items": {
                        "type": "object",
                        "properties": {
                            "op": {
                                "type": "string",
                                "enum": ["set", "event", "del"],
                                "description": "set=设置画像, event=记录事件, del=删除画像"
                            },
                            "key": {
                                "type": "string",
                                "description": "画像键名(set/del时必填)"
                            },
                            "value": {
                                "type": "string",
                                "description": "画像值(set时)或事件描述(event时)"
                            }
                        },
                        "required": ["op"]
                    }
                }
            },
            "required": ["operations"]
        }
    )
    async def memory_update(self, event: KiraMessageBatchEvent, operations: list) -> str:
        if not self.db:
            return "Error: memory database not initialized"

        user_id = self._get_primary_user_id(event)
        if user_id == "unknown":
            return "Error: cannot determine user_id"

        results = []
        for item in operations:
            if not isinstance(item, dict):
                results.append("skip: invalid operation (not an object)")
                continue
            op = item.get("op", "")
            key = item.get("key", "")
            value = item.get("value", "")

            if op == "set":
                if not key or not value:
                    results.append("skip: set requires key+value")
                    continue
                is_update = self.db.profile_exists(user_id, key)
                if not is_update:
                    count = self.db.get_profile_count(user_id)
                    if count >= self.max_profiles:
                        results.append(f"skip: profile limit ({self.max_profiles})")
                        continue
                self.db.save_profile(user_id, key, value)
                results.append(f"{'updated' if is_update else 'set'} {key}={value}")

            elif op == "event":
                if not value:
                    results.append("skip: event requires value")
                    continue
                self.db.save_event(user_id, value)
                self.db.cleanup_old_events(user_id, keep=self.max_event_keep)
                results.append(f"event: {value}")

            elif op == "del":
                if not key:
                    results.append("skip: del requires key")
                    continue
                removed = self.db.remove_profile(user_id, key)
                results.append(f"del {key}: {'ok' if removed else 'not found'}")

            else:
                results.append(f"skip: unknown op '{op}'")

        logger.info(f"memory_update for {user_id}: {len(operations)} ops → {results}")
        return f"已完成 {len(results)} 项记忆操作: " + "; ".join(results)

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

        # ── Part 2: Skill one-liner list ────────────────────────────
        skill_line = ""
        if self._registered_skill_names:
            names = []
            for sn in self._registered_skill_names:
                sk = self.skill_router.get_skill(sn)
                if sk:
                    names.append(sk.name)
            if names:
                skill_line = SKILL_FEW_SHOT_HEADER + ", ".join(names) + "\n"

        # ── Inject: memory data into "memory", skill list into "tools"
        injected_memory = False
        for p in req.system_prompt:
            if p.name == "memory" and memory_context:
                p.content += f"\n{memory_context}"
                injected_memory = True
            if p.name == "tools" and skill_line:
                p.content += skill_line

        # Fallback: if no "memory" section found
        if not injected_memory and memory_context and req.system_prompt:
            req.system_prompt[-1].content += f"\n{memory_context}"
