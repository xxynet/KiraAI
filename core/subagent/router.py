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

    def parse_subagent_id(self, session: str) -> Optional[str]:
        if not self.is_subagent_session(session):
            return None
        parts = session.split(":", maxsplit=2)
        if len(parts) >= 3:
            return parts[2]
        return None

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
        subagent_id = self.parse_subagent_id(session)
        if not subagent_id:
            return []
        config = self.registry.get_config(subagent_id)
        if not config:
            return []
        # 尝试从 session 或 app 缓存获取实例
        for session_map in self._session_instances.values():
            inst = session_map.get(subagent_id)
            if inst:
                return inst.fetch_memory()
        inst = self._app_instances.get(subagent_id)
        if inst:
            return inst.fetch_memory()
        return []

    def _get_instance_for_memory(self, session: str):
        subagent_id = self.parse_subagent_id(session)
        if not subagent_id:
            return None
        config = self.registry.get_config(subagent_id)
        if not config:
            return None
        # 优先查找已有实例
        for session_map in self._session_instances.values():
            inst = session_map.get(subagent_id)
            if inst:
                return inst
        inst = self._app_instances.get(subagent_id)
        if inst:
            return inst
        # 如果没有实例，根据生命周期创建
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
        subagent_id = self.parse_subagent_id(session)
        if not subagent_id:
            return
        self._session_instances.pop(session, None)
        # app_scope 不随会话删除

    def cleanup_session(self, session_id: str):
        """清理某主会话关联的所有 session 生命周期 SubAgent"""
        removed = self._session_instances.pop(session_id, None)
        if removed:
            logger.info(f"Cleaned up SubAgent instances for session {session_id}")
