import asyncio
import json

from fastapi import Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core.logging_manager import get_logger, log_cache_manager
from core.utils.pkg_installer import build_install_command, describe_backend
from webui.routes.auth import require_auth
from webui.routes.base import RouteDefinition, Routes

logger = get_logger("webui", "blue")


class InstallPackagesRequest(BaseModel):
    packages: str
    pypi_mirror: str | None = None


class LogsRoutes(Routes):
    _install_task: asyncio.Task | None = None
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
        """POST endpoint that kicks off a package install in background."""
        packages = body.packages.strip()
        if not packages:
            raise HTTPException(status_code=400, detail="No packages specified")
        if self._install_task and not self._install_task.done():
            raise HTTPException(status_code=409, detail="Another installation is already in progress")
        self._install_task = asyncio.create_task(self._run_package_install(packages, body.pypi_mirror))
        return {"status": "started"}

    async def _run_package_install(self, packages: str, pypi_mirror: str | None = None):
        """Background task: run the package install and stream output to the logger."""
        # Fall back to global pypi_mirror config if user didn't provide one
        if not pypi_mirror:
            config = getattr(self.lifecycle, "kira_config", None)
            if config:
                pypi_mirror = (config.get("network") or {}).get("pypi_mirror") or None

        logger.info(f"Starting package installation: {packages}")
        try:
            cmd = build_install_command(packages.split(), pypi_mirror, unbuffered=True)
        except RuntimeError as e:
            logger.error(f"Package installation error: {e}")
            return
        logger.info(f"Using installer backend: {describe_backend()}")
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
