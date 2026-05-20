import os

from fastapi import Depends

from webui.routes.auth import require_auth
from webui.routes.base import RouteDefinition, Routes

RESTART_EXIT_CODE = 42


class SystemRoutes(Routes):
    def get_routes(self):
        return [
            RouteDefinition(
                path="/api/system/restart",
                methods=["POST"],
                endpoint=self.restart,
                tags=["system"],
                dependencies=[Depends(require_auth)],
            ),
        ]

    async def restart(self):
        await self.lifecycle.stop()
        if self.lifecycle.uvicorn_server:
            self.lifecycle.uvicorn_server.should_exit = True
        # Give the response a moment to be sent, then exit with restart code
        import asyncio
        asyncio.get_event_loop().call_later(0.5, os._exit, RESTART_EXIT_CODE)
        return {"status": "restarting"}
