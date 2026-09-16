from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal


QRCodeLoginStatus = Literal["pending", "confirmed", "expired", "denied", "error"]


@dataclass(frozen=True)
class QRCodeLoginStartResult:
    qr_content: str
    poll_interval: int = 2
    expires_in: int = 300


@dataclass(frozen=True)
class QRCodeLoginPollResult:
    status: QRCodeLoginStatus
    config_patch: dict[str, Any] = field(default_factory=dict)
    message: str = ""


class QRCodeLoginHandler(ABC):
    """Handle a QR-code login flow without creating an adapter instance."""

    @abstractmethod
    async def start(self) -> QRCodeLoginStartResult:
        """Start the login flow and return the QR-code payload."""

    @abstractmethod
    async def poll(self) -> QRCodeLoginPollResult:
        """Poll the login flow once and return its current state."""

    async def close(self) -> None:
        """Release resources held by the login flow."""
