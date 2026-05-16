from __future__ import annotations

import asyncio
import time
import uuid
from typing import Optional

from core.logging_manager import get_logger
from .models import SubAgentConfig, SubAgentRequest, SubAgentResponse
from .router import SubAgentRouter

logger = get_logger("subagent", "magenta")


class SubAgentClient:
    """主 Agent 侧调用客户端：提供同步/异步调用 SubAgent 的接口"""

    def __init__(self, router: SubAgentRouter):
        self.router = router
        self._call_depth = 0
        self._max_depth = 1  # 禁止嵌套调用
        self._depth_lock = asyncio.Lock()

    def _generate_correlation_id(self) -> str:
        return f"sub_{uuid.uuid4().hex[:12]}_{int(time.time() * 1000)}"

    async def call(
        self,
        subagent_id: str,
        content: str,
        task_type: str = "general",
        session_id: Optional[str] = None,
        metadata: Optional[dict] = None,
        timeout: Optional[float] = None,
    ) -> SubAgentResponse:
        """同步调用 SubAgent，等待结果返回（带超时）"""
        async with self._depth_lock:
            if self._call_depth >= self._max_depth:
                return SubAgentResponse(
                    correlation_id="",
                    status="cancelled",
                    err="Nested SubAgent calls are not allowed",
                )
            self._call_depth += 1

        config = self.router.registry.get_config(subagent_id)
        if not config:
            return SubAgentResponse(
                correlation_id="",
                status="cancelled",
                err=f"SubAgent '{subagent_id}' not found",
            )

        correlation_id = self._generate_correlation_id()
        meta = dict(metadata or {})
        meta["subagent_id"] = subagent_id

        request = SubAgentRequest(
            correlation_id=correlation_id,
            task_type=task_type,
            content=content,
            metadata=meta,
        )

        effective_timeout = timeout or config.timeout

        try:
            result = await asyncio.wait_for(
                self.router.dispatch(request, session_id=session_id),
                timeout=effective_timeout,
            )
            return result
        except asyncio.TimeoutError:
            logger.warning(f"SubAgent '{subagent_id}' call timeout (correlation_id={correlation_id})")
            return SubAgentResponse(
                correlation_id=correlation_id,
                status="timeout",
                err=f"SubAgent call timed out after {effective_timeout}s",
            )
        except Exception as e:
            logger.error(f"SubAgent '{subagent_id}' call error: {e}")
            return SubAgentResponse(
                correlation_id=correlation_id,
                status="model_error",
                err=str(e),
            )
        finally:
            async with self._depth_lock:
                self._call_depth -= 1

    async def call_with_retry(
        self,
        subagent_id: str,
        content: str,
        task_type: str = "general",
        session_id: Optional[str] = None,
        metadata: Optional[dict] = None,
        max_retries: int = 2,
        base_delay: float = 1.0,
    ) -> SubAgentResponse:
        """带有限重试和线性退避的调用"""
        last_result = None
        for attempt in range(max_retries + 1):
            result = await self.call(
                subagent_id=subagent_id,
                content=content,
                task_type=task_type,
                session_id=session_id,
                metadata=metadata,
            )
            last_result = result
            if result.status == "success":
                return result
            if result.status in ("cancelled",):
                return result
            if attempt < max_retries:
                delay = base_delay * (attempt + 1)
                logger.info(f"SubAgent '{subagent_id}' retry {attempt + 1}/{max_retries} after {delay}s")
                await asyncio.sleep(delay)
        return last_result
