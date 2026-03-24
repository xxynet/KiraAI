import json
from typing import Optional

from fastapi import Depends, Header, HTTPException
from fastapi.responses import StreamingResponse

from core.logging_manager import get_logger, log_cache_manager
from webui.routes.auth import require_auth
from webui.routes.base import RouteDefinition, Routes
from webui.utils import _verify_jwt_token

logger = get_logger("webui", "blue")


class LogsRoutes(Routes):
    def get_routes(self):
        return [
            RouteDefinition(
                path="/api/live-log",
                methods=["GET"],
                endpoint=self.live_log,
                tags=["logs"],
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
        ]

    async def live_log(
        self,
        authorization: Optional[str] = Header(None),
        token: Optional[str] = None,
    ):
        """SSE endpoint for real-time log streaming."""
        jwt_token = None
        if authorization and authorization.startswith("Bearer "):
            jwt_token = authorization.split(" ", 1)[1]
        elif token:
            jwt_token = token

        if jwt_token:
            try:
                _verify_jwt_token(jwt_token)
            except HTTPException:
                raise

        async def event_generator():
            que = log_cache_manager.add_queue()
            try:
                while True:
                    log_entry = await que.get()
                    data = json.dumps(log_entry, ensure_ascii=False)
                    yield f"data: {data}\n\n"
            except Exception as e:
                logger.error(f"Error in SSE stream: {e}")
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
