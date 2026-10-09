from __future__ import annotations

import time
from typing import Callable, TYPE_CHECKING

from core.chat.message_utils import KiraMessageEvent, KiraMessageBatchEvent
from core.chat.session_buffer import SessionBufferManager

if TYPE_CHECKING:
    from core.event_bus import EventBus


async def publish_buffered_messages(
    buffers: SessionBufferManager,
    event_bus: EventBus,
    sid: str,
    *,
    extra_event: KiraMessageEvent | None = None,
    filter_fn: Callable[[KiraMessageEvent], bool] | None = None,
) -> bool:
    """Publish buffered events matching a synchronous predicate, or all events by default."""
    pending_messages = await buffers.flush_messages(
        sid, extra_event=extra_event, filter_fn=filter_fn)
    if not pending_messages:
        return False
    last_event = pending_messages[-1]
    supported_elements = last_event.supported_elements
    batch_msg = KiraMessageBatchEvent(
        supported_elements=supported_elements,
        timestamp=int(time.time()),
        adapter=last_event.adapter,
        session=last_event.session,
        messages=[m.message for m in pending_messages]
    )
    await event_bus.publish(batch_msg)
    return True
