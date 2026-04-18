from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
import uuid


class TelemetryEventType:
    SYSTEM_STARTUP = "system_startup"
    SYSTEM_SHUTDOWN = "system_shutdown"
    MESSAGE_STATS = "message_stats"
    HEARTBEAT = "heartbeat"
    UUID_REQUEST = "uuid_request"
    LLM_REQUEST = "llm_request"
    TELEMETRY_DISABLED = "telemetry_disabled"
    TELEMETRY_ENABLED = "telemetry_enabled"


@dataclass
class TelemetryEvent:
    event_type: str
    data: dict[str, Any]
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    client_uuid: Optional[str] = None
    signature: Optional[str] = None

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "client_uuid": self.client_uuid,
            "data": self.data,
        }
        if self.signature:
            payload["signature"] = self.signature
        return payload
