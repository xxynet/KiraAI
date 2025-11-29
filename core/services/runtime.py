import asyncio
from asyncio import Queue
from typing import Dict, Any, Optional, Union
from utils.adapter_utils import IMAdapter
from core.logging_manager import get_logger


logger = get_logger("runtime", "blue")


_adapters: Dict[str, Union[IMAdapter]] = {}
_loop: Optional[asyncio.AbstractEventLoop] = None
_event_bus: Optional[Queue] = None


def set_adapters(adapters: Dict[str, Union[IMAdapter]]):
    global _adapters
    _adapters = adapters or {}
    logger.info(f"Adapters set: {list(adapters.keys())}")


def get_adapters() -> Dict[str, Any]:
    return _adapters


def get_adapter_by_name(adapter_name: str):
    return _adapters.get(adapter_name)


def set_event_bus(event_bus):
    global _event_bus
    _event_bus = event_bus


def get_event_bus() -> Queue:
    return _event_bus


def set_loop(loop: asyncio.AbstractEventLoop):
    global _loop
    _loop = loop


def get_loop() -> Optional[asyncio.AbstractEventLoop]:
    return _loop
