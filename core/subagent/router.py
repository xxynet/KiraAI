from __future__ import annotations

import asyncio
from typing import Dict, Optional

from core.logging_manager import get_logger
from core.chat.session_manager import SessionManager
from .models import SubAgentConfig, SubAgentRequest, SubAgentResponse
from .registry import SubAgentRegistry
from .subagent import SubAgent

logger = get_logger("subagent", "magenta")


class SubAgentRouter:
    """SubAgent 路由层：挂载到 SessionManager，管理 SubAgent 实例与消息分发"""

    def __init__(
        self,
        registry: SubAgentRegistry,
        provider_mgr,
        llm_api,
        prompt_manager=None,
    ):
        self.registry = registry
        self.provider_mgr = provider_mgr
        self.llm_api = llm_api
        self.prompt_manager = prompt_manager

        # session_scope 实例缓存: {session_id: {subagent_id: SubAgent}}
        self._session_instances: Dict[str, Dict[str, SubAgent]] = {}
        # app_scope 实例缓存: {subagent_id: SubAgent}
        self._app_instances: Dict[str, SubAgent] = {}

        # 挂起等待的 Future: {correlation_id: asyncio.Future}
        self._pending_futures: Dict[str, asyncio.Future] = {}

    def _get_or_create_instance(self, config: SubAgentConfig, session_id: Optional[str] = None) -> SubAgent:
        lifecycle = config.lifecycle

        if lifecycle == "app_scope":
            inst = self._app_instances.get(config.subagent_id)
            if inst is None:
                inst = SubAgent(config, self.provider_mgr, self.llm_api, self.prompt_manager)
                self._app_instances[config.subagent_id] = inst
                self.registry.set_instance(config.subagent_id, inst)
            return inst

        if lifecycle == "session" and session_id:
            session_map = self._session_instances.setdefault(session_id, {})
            inst = session_map.get(config.subagent_id)
            if inst is None:
                inst = SubAgent(config, self.provider_mgr, self.llm_api, self.prompt_manager)
                session_map[config.subagent_id] = inst
            return inst

        # on_demand: 每次创建新实例
        return SubAgent(config, self.provider_mgr, self.llm_api, self.prompt_manager)

    def is_subagent_session(self, session: str) -> bool:
        return isinstance(session, str) and session.startswith("sub:dm:")

    def parse_subagent_session(self, session: str) -> tuple[Optional[str], Optional[str]]:
        """Parse a subagent session string into (parent_session_id, subagent_id).

        Expected format: sub:dm:<parent_session>:<subagent_id>
        subagent_id must not contain ':' to avoid ambiguity.
        """
        if not self.is_subagent_session(session):
            return None, None
        parts = session.split(":", maxsplit=3)
        if len(parts) < 4:
            return None, None
        parent_session_id = parts[2]
        subagent_id = parts[3]
        # subagent_id 含 ':' 会导致后续解析错位，直接拒绝
        if ":" in subagent_id:
            logger.warning(f"Invalid subagent_id contains ':' in session string: {session}")
            return None, None
        return parent_session_id, subagent_id

    def parse_subagent_id(self, session: str) -> Optional[str]:
        _, subagent_id = self.parse_subagent_session(session)
        return subagent_id

    async def dispatch(self, request: SubAgentRequest, session_id: Optional[str] = None) -> SubAgentResponse:
        """同步调用：派发请求到对应 SubAgent 并等待结果"""
        subagent_id = request.metadata.get("subagent_id")
        if not subagent_id:
            return SubAgentResponse(
                correlation_id=request.correlation_id,
                status="cancelled",
                err="Missing subagent_id in request metadata",
            )

        config = self.registry.get_config(subagent_id)
        if not config:
            return SubAgentResponse(
                correlation_id=request.correlation_id,
                status="cancelled",
                err=f"SubAgent '{subagent_id}' not registered",
            )

        inst = self._get_or_create_instance(config, session_id)
        return await inst.execute(request)

    def fetch_memory(self, session: str) -> list:
        parent_session_id, subagent_id = self.parse_subagent_session(session)
        if not subagent_id:
            return []
        config = self.registry.get_config(subagent_id)
        if not config:
            return []
        if parent_session_id and parent_session_id in self._session_instances:
            inst = self._session_instances[parent_session_id].get(subagent_id)
            if inst:
                return inst.fetch_memory()
        inst = self._app_instances.get(subagent_id)
        if inst:
            return inst.fetch_memory()
        return []

    def _get_instance_for_memory(self, session: str):
        parent_session_id, subagent_id = self.parse_subagent_session(session)
        if not subagent_id:
            return None
        config = self.registry.get_config(subagent_id)
        if not config:
            return None
        if parent_session_id and parent_session_id in self._session_instances:
            inst = self._session_instances[parent_session_id].get(subagent_id)
            if inst:
                return inst
        inst = self._app_instances.get(subagent_id)
        if inst:
            return inst
        if config.lifecycle == "app_scope":
            return self._get_or_create_instance(config)
        return None

    def write_memory(self, session: str, memory: list):
        inst = self._get_instance_for_memory(session)
        if inst:
            inst.write_memory(memory)

    def update_memory(self, session: str, new_chunk: list):
        inst = self._get_instance_for_memory(session)
        if inst:
            inst.update_memory(new_chunk)

    def delete_session(self, session: str):
        parent_session_id, subagent_id = self.parse_subagent_session(session)
        if not subagent_id:
            return
        if parent_session_id and parent_session_id in self._session_instances:
            session_map = self._session_instances[parent_session_id]
            session_map.pop(subagent_id, None)
            if not session_map:
                self._session_instances.pop(parent_session_id, None)
        # app_scope 不随会话删除

    def cleanup_session(self, session_id: str):
        """清理某主会话关联的所有 session 生命周期 SubAgent"""
        removed = self._session_instances.pop(session_id, None)
        if removed:
            logger.info(f"Cleaned up SubAgent instances for session {session_id}")
