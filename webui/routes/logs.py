import asyncio
import json
import sys

from fastapi import Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core.logging_manager import get_logger, log_cache_manager
from webui.routes.auth import require_auth
from webui.routes.base import RouteDefinition, Routes

logger = get_logger("webui", "blue")


class InstallPackagesRequest(BaseModel):
    packages: str
    pypi_mirror: str | None = None


class LogsRoutes(Routes):
    def get_routes(self):
        return [
            RouteDefinition(
                path="/api/live-log",
                methods=["GET"],
                endpoint=self.live_log,
                tags=["logs"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/log-history",
                methods=["GET"],
                endpoint=self.get_log_history,
                tags=["logs"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/log-config",
                methods=["GET"],
                endpoint=self.get_log_config,
                tags=["logs"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/install-packages",
                methods=["POST"],
                endpoint=self.install_packages,
                tags=["logs"],
                dependencies=[Depends(require_auth)],
            ),
        ]

    async def live_log(self):
        """SSE endpoint for real-time log streaming."""

        async def event_generator():
            que = log_cache_manager.add_queue()
            try:
                while True:
                    try:
                        log_entry = await que.get()
                    except asyncio.CancelledError:
                        break
                    data = json.dumps(log_entry, ensure_ascii=False)
                    yield f"data: {data}\n\n"
            finally:
                log_cache_manager.remove_queue(que)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    async def get_log_history(self, limit: int = 100):
        """Get historical log entries from log cache."""
        try:
            cached_logs = log_cache_manager.get_cache()
            if limit > 0:
                recent_logs = cached_logs[-limit:] if len(cached_logs) > limit else cached_logs
            else:
                recent_logs = cached_logs

            logs = []
            for log in recent_logs:
                logs.append({
                    "time": log.get("time", ""),
                    "level": log.get("level", "INFO"),
                    "name": log.get("name", ""),
                    "message": log.get("message", ""),
                    "color": log.get("color", "blue"),
                    "raw": f"{log.get('time', '')} {log.get('level', 'INFO')} [{log.get('name', '')}] {log.get('message', '')}",
                })

            return {"logs": logs, "total": len(logs)}
        except Exception as e:
            logger.error(f"Error reading log cache: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to read log cache: {str(e)}")

    async def get_log_config(self):
        """Get log configuration including max queue size."""
        try:
            from core.logging_manager import MAX_QUEUE_SIZE
            return {"maxQueueSize": MAX_QUEUE_SIZE}
        except Exception as e:
            logger.error(f"Error reading log config: {e}")
            return {"maxQueueSize": 100}

    async def install_packages(self, body: InstallPackagesRequest):
        """POST endpoint that kicks off pip install in background."""
        packages = body.packages.strip()
        if not packages:
            raise HTTPException(status_code=400, detail="No packages specified")
        asyncio.create_task(self._run_pip_install(packages, body.pypi_mirror))
        return {"status": "started"}

    async def _run_pip_install(self, packages: str, pypi_mirror: str | None = None):
        """Background task: run pip install and stream output to the logger."""
        # Fall back to global pypi_mirror config if user didn't provide one
        if not pypi_mirror:
            config = getattr(self.lifecycle, "kira_config", None)
            if config:
                pypi_mirror = (config.get("network") or {}).get("pypi_mirror") or None

        logger.info(f"Starting package installation: {packages}")
        cmd = [sys.executable, "-u", "-m", "pip", "install", *packages.split()]
        if pypi_mirror:
            if pypi_mirror.startswith(("http://", "https://")):
                cmd.extend(["-i", pypi_mirror])
            else:
                logger.warning(f"Ignoring invalid pypi_mirror: {pypi_mirror}")
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            assert proc.stdout is not None
            async for raw_line in proc.stdout:
                line = raw_line.decode(errors="replace").rstrip()
                if line:
                    logger.info(line)
            await proc.wait()
            if proc.returncode == 0:
                logger.info("Package installation completed successfully")
            else:
                logger.error(f"Package installation failed with exit code {proc.returncode}")
        except Exception as e:
            logger.error(f"Package installation error: {e}")
