import asyncio
from asyncio import Queue
from typing import Dict, Any, Optional, Union
from utils.adapter_utils import IMAdapter, SocialMediaAdapter
from core.logging_manager import get_logger


logger = get_logger("runtime", "blue")


_adapters: Dict[str, Union[IMAdapter, SocialMediaAdapter]] = {}
_event_queue: Optional[Queue] = None


def set_adapters(adapters: Dict[str, Union[IMAdapter]]):
    global _adapters
    _adapters = adapters or {}
    logger.info(f"Adapters set: {list(adapters.keys())}")


def get_adapters() -> Dict[str, Any]:
    return _adapters


def get_adapter_by_name(adapter_name: str):
    return _adapters.get(adapter_name)


def set_event_bus(event_queue):
    global _event_queue
    _event_queue = event_queue


def get_event_bus() -> Queue:
    return _event_queue
