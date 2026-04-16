import asyncio
import hmac
import hashlib
import json
import platform as sys_platform
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from core.config import KiraConfig, VERSION
from core.logging_manager import get_logger
from core.utils.path_utils import get_data_path
from core.statistics import Statistics

from .models import TelemetryEvent, TelemetryEventType

logger = get_logger("telemetry", "green")

TELEMETRY_CONFIG_PATH = get_data_path() / "telemetry_config.json"


class TelemetryClient:
    """
    Telemetry client for KiraAI.
    Handles UUID acquisition, event signing, and asynchronous event submission.
    All network errors are caught and logged to avoid blocking the main application.
    """

    def __init__(self, config: KiraConfig, stats: Optional[Statistics] = None):
        self.config = config
        self.stats = stats
        self.telemetry_config = config.get_config("telemetry", default={})

        self.enabled: bool = self.telemetry_config.get("enabled", True)
        self.client_uuid: Optional[str] = self.telemetry_config.get("client_uuid")
        self.secret_key: Optional[str] = self.telemetry_config.get("secret_key")

        self.server_url: str = "https://telemetry.kira-ai.top/api/v1"
        self.heartbeat_interval: int = 300  # 5 minutes

        self._http_client: Optional[httpx.AsyncClient] = None
        self._send_queue: asyncio.Queue[TelemetryEvent] = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def initialize(self) -> None:
        """Asynchronous initialization: ensure HTTP client and UUID are ready."""
        if not self.enabled:
            logger.info("Telemetry is disabled.")
            return

        self._http_client = httpx.AsyncClient(timeout=30.0)

        if not self.client_uuid or not self.secret_key:
            await self._request_uuid()

        if self.client_uuid and self.secret_key:
            self._worker_task = asyncio.create_task(self._send_worker())
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            self.send_system_startup()
            logger.info(f"Telemetry client initialized (UUID: {self.client_uuid}).")
        else:
            logger.warning("Telemetry client failed to acquire UUID; events will be dropped.")

    async def shutdown(self) -> None:
        """Graceful shutdown: flush pending events and close HTTP client."""
        self._shutdown_event.set()

        started_ts = self.stats.get_stats("started_ts") if self.stats else None
        if started_ts:
            uptime_duration_ms = int((datetime.now(timezone.utc).timestamp() - started_ts) * 1000)
            self.send_system_shutdown(uptime_duration_ms)

        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        if self._worker_task:
            try:
                await asyncio.wait_for(self._worker_task, timeout=5.0)
            except asyncio.TimeoutError:
                self._worker_task.cancel()

        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

        logger.info("Telemetry client shut down.")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def is_enabled(self) -> bool:
        return self.enabled and self.client_uuid is not None and self.secret_key is not None

    def send_event(self, event_type: str, data: dict[str, Any], force: bool = False) -> None:
        """
        Fire-and-forget event submission.
        If the worker is not running, the event is silently dropped.
        Use ``force=True`` to bypass the local enabled check (used for
        telemetry state-change events themselves).
        """
        if not force and not self.is_enabled():
            return

        event = TelemetryEvent(
            event_type=event_type,
            data=data,
            client_uuid=self.client_uuid,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        try:
            self._send_queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("Telemetry send queue is full; dropping event.")

    async def toggle_telemetry(self, enabled: bool) -> bool:
        """
        Enable or disable telemetry locally.
        When disabling, emits a telemetry_disabled event so the server
        can process the state change upon receiving it.
        """
        if not enabled:
            if not self.client_uuid or not self.secret_key or not self._http_client:
                logger.error("Cannot toggle telemetry: client not initialized.")
                return False

            self.send_event(TelemetryEventType.TELEMETRY_DISABLED, {
                "reason": "user_requested",
                "client_uuid": self.client_uuid,
            }, force=True)

        self.enabled = enabled
        self._persist_config()
        logger.info(f"Telemetry {'enabled' if enabled else 'disabled'}.")
        return True

    async def reopen_telemetry(self) -> bool:
        """
        Re-enable telemetry and notify the server via event.
        Initializes the HTTP client and background workers if needed.
        Returns True on success.
        """
        if self.enabled and self._http_client:
            logger.info("Telemetry is already enabled.")
            return True

        if not self._http_client:
            self._http_client = httpx.AsyncClient(timeout=30.0)

        if not self.client_uuid or not self.secret_key:
            await self._request_uuid()

        if not self.client_uuid or not self.secret_key:
            logger.error("Cannot reopen telemetry: failed to acquire UUID.")
            return False

        # Start background workers if they are not running
        if not self._worker_task or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._send_worker())
        if not self._heartbeat_task or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        self.enabled = True
        self._persist_config()

        # Emit event after enabling so it is actually sent
        self.send_event(TelemetryEventType.TELEMETRY_ENABLED, {
            "reason": "user_requested",
            "client_uuid": self.client_uuid,
        }, force=True)

        logger.info("Telemetry reopened.")
        return True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    async def _request_uuid(self) -> None:
        """Request a new client UUID and secret key from the telemetry server."""
        if not self._http_client:
            return

        url = f"{self.server_url}/uuid"
        payload: dict[str, Any] = {}

        try:
            resp = await self._http_client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f"Failed to request telemetry UUID: {e}")
            return

        self.client_uuid = data.get("client_uuid")
        self.secret_key = data.get("secret_key")

        if self.client_uuid and self.secret_key:
            self._persist_config()
            logger.info("Telemetry UUID acquired and persisted.")
        else:
            logger.error("Telemetry server returned invalid UUID response.")

    def _persist_config(self) -> None:
        """Persist telemetry settings back to the global KiraConfig."""
        if not hasattr(self.config, "telemetry"):
            self.config["telemetry"] = {}

        self.config["telemetry"].update({
            "enabled": self.enabled,
            "client_uuid": self.client_uuid,
            "secret_key": self.secret_key,
        })
        self.config.save_config()

    def _sign_payload(self, payload: dict[str, Any]) -> str:
        """Generate HMAC-SHA256 signature for a payload (excluding 'signature')."""
        if not self.secret_key:
            raise RuntimeError("Cannot sign payload without secret_key")

        payload_copy = dict(payload)
        payload_copy.pop("signature", None)
        canonical = json.dumps(payload_copy, sort_keys=True, separators=(",", ":"))
        return hmac.new(
            self.secret_key.encode("utf-8"),
            canonical.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    async def _heartbeat_loop(self) -> None:
        """Background loop that sends heartbeat events periodically."""
        while not self._shutdown_event.is_set():
            try:
                await asyncio.wait_for(self._shutdown_event.wait(), timeout=float(self.heartbeat_interval))
            except asyncio.TimeoutError:
                pass
            else:
                break

            started_ts = self.stats.get_stats("started_ts") if self.stats else None
            if started_ts:
                uptime_ms = int((datetime.now(timezone.utc).timestamp() - started_ts) * 1000)
                self.send_heartbeat(uptime_ms=uptime_ms)

    async def _send_worker(self) -> None:
        """Background worker that consumes the queue and sends events."""
        url = f"{self.server_url}/events"

        while not self._shutdown_event.is_set() or not self._send_queue.empty():
            try:
                event = await asyncio.wait_for(self._send_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            payload = event.to_payload()
            try:
                payload["signature"] = self._sign_payload(payload)
            except Exception as e:
                logger.error(f"Failed to sign telemetry event: {e}")
                continue

            try:
                resp = await self._http_client.post(url, json=payload)
                resp.raise_for_status()
                logger.debug(
                    f"Telemetry event sent: {event.event_id} "
                    f"type={event.event_type} payload={json.dumps(payload, ensure_ascii=False)}"
                )
                logger.debug(f"Telemetry server response: {resp.text}")
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 403:
                    logger.warning("Telemetry rejected by server (disabled or bad signature).")
                else:
                    logger.warning(f"Telemetry server returned {e.response.status_code}: {e}")
            except Exception as e:
                logger.warning(f"Failed to send telemetry event: {e}")

    # ------------------------------------------------------------------
    # Convenience helpers for common events
    # ------------------------------------------------------------------
    def send_system_startup(self, python_version: str = "") -> None:
        self.send_event(TelemetryEventType.SYSTEM_STARTUP, {
            "kira_ai_version": VERSION,
            "python_version": python_version or sys_platform.python_version(),
            "platform": sys_platform.platform(),
        })

    def send_system_shutdown(self, uptime_duration_ms: int) -> None:
        self.send_event(TelemetryEventType.SYSTEM_SHUTDOWN, {
            "uptime_duration_ms": uptime_duration_ms,
        })

    def send_heartbeat(self, uptime_ms: int, active_connections: int = 0) -> None:
        self.send_event(TelemetryEventType.HEARTBEAT, {
            "uptime_ms": uptime_ms,
            "active_connections": active_connections,
        })

    def send_llm_request(self, model_name: str, prompt_tokens: int, completion_tokens: int,
                         response_time_ms: int, success: bool) -> None:
        self.send_event(TelemetryEventType.LLM_REQUEST, {
            "model_name": model_name,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "response_time_ms": response_time_ms,
            "success": success,
        })

    def send_message_stats(self, total_messages: int, messages_by_platform: dict[str, int],
                           time_window_minutes: int = 60) -> None:
        self.send_event(TelemetryEventType.MESSAGE_STATS, {
            "total_messages": total_messages,
            "messages_by_platform": messages_by_platform,
            "time_window_minutes": time_window_minutes,
        })
