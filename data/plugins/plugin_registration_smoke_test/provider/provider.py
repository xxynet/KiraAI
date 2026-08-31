from typing import ClassVar

from core.provider import BaseProvider


class PluginRegistrationSmokeProvider(BaseProvider):
    models: ClassVar[dict] = {}
