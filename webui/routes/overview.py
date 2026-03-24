import os
import time

from fastapi import Depends
import psutil

from core.logging_manager import get_logger
from webui.models import OverviewResponse
from webui.routes.auth import require_auth
from webui.routes.base import RouteDefinition, Routes

logger = get_logger("webui", "blue")


class OverviewRoutes(Routes):
    def get_routes(self):
        return [
            RouteDefinition(
                path="/api/overview",
                methods=["GET"],
                endpoint=self.get_overview,
                response_model=OverviewResponse,
                tags=["overview"],
                dependencies=[Depends(require_auth)],
            ),
        ]

    async def get_overview(self):
        runtime_duration = 0
        if self.lifecycle and self.lifecycle.stats:
            started_ts = self.lifecycle.stats.get_stats("started_ts")
            if started_ts:
                runtime_duration = int(time.time()) - started_ts

        memory_usage = 0
        total_memory = 0
        try:
            process = psutil.Process(os.getpid())
            memory_info = process.memory_info()
            memory_usage = int(memory_info.rss / (1024 * 1024))
            total_memory = int(psutil.virtual_memory().total / (1024 * 1024))
        except Exception as e:
            logger.warning(f"Failed to get memory info: {e}")

        total_adapters = 0
        active_adapters = 0
        if self.lifecycle and getattr(self.lifecycle, "adapter_manager", None):
            try:
                adapter_mgr = self.lifecycle.adapter_manager
                adapter_infos = adapter_mgr.get_adapter_infos()
                total_adapters = len(adapter_infos)
                running_adapters = set(adapter_mgr.get_adapters().keys())
                active_adapters = len(
                    [
                        info
                        for info in adapter_infos
                        if info.enabled and info.name in running_adapters
                    ]
                )
            except Exception as e:
                logger.error(f"Failed to collect adapter stats for overview: {e}")

        total_providers = 0
        active_providers = 0
        if self.lifecycle and getattr(self.lifecycle, "provider_manager", None):
            try:
                providers_config = self.lifecycle.kira_config.get("providers", {}) or {}
                total_providers = len(providers_config)
                active_providers = len(
                    [
                        provider_id
                        for provider_id in providers_config.keys()
                        if provider_id in self.lifecycle.provider_manager._providers
                    ]
                )
            except Exception as e:
                logger.error(f"Failed to collect provider stats for overview: {e}")

        total_messages = 0
        if self.lifecycle and getattr(self.lifecycle, "stats", None):
            try:
                message_stats = self.lifecycle.stats.get_stats("messages") or {}
                total_messages = int(message_stats.get("total_messages", 0) or 0)
            except Exception as e:
                logger.error(f"Failed to collect message stats for overview: {e}")

        return OverviewResponse(
            total_adapters=total_adapters,
            active_adapters=active_adapters,
            total_providers=total_providers,
            active_providers=active_providers,
            total_messages=total_messages,
            system_status="running" if self.lifecycle else "unknown",
            runtime_duration=runtime_duration,
            memory_usage=memory_usage,
            total_memory=total_memory,
        )
