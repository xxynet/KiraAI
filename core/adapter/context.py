from __future__ import annotations

import asyncio
from dataclasses import dataclass

from .adapter_info import AdapterInfo


@dataclass
class AdapterContext:
    """Dependencies supplied to an adapter instance."""

    info: AdapterInfo
    event_queue: asyncio.Queue
