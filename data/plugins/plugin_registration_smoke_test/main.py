from core.plugin import BasePlugin


class PluginRegistrationSmokeTest(BasePlugin):
    async def initialize(self):
        await self.ctx.register_provider("provider")
        await self.ctx.register_adapter("adapter")

    async def terminate(self):
        pass