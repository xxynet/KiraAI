import asyncio
import hmac
import hashlib
import json
import os
import time
import platform as sys_platform
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from core.config import KiraConfig, VERSION
from core.logging_manager import get_logger
from core.utils.path_utils import get_data_path
from core.statistics import Statistics
from core.db.service import DatabaseService

from .models import TelemetryEvent, TelemetryEventType

logger = get_logger("telemetry", "green")

TELEMETRY_CONFIG_PATH = get_data_path() / "telemetry_config.json"


class TelemetryClient:
    """
    Telemetry client for KiraAI.
    Handles UUID acquisition, event signing, and asynchronous event submission.
    All network errors are caught and logged to avoid blocking the main application.
    """

    def __init__(self, db: DatabaseService, config: KiraConfig, stats: Optional[Statistics] = None):
        self.db = db
        self.config = config
        self.stats = stats
        self.telemetry_config = config.get_config("telemetry", default={})

        self.enabled: bool = self.telemetry_config.get("enabled", True)
        self.client_uuid: Optional[str] = self.telemetry_config.get("client_uuid")
        self.secret_key: Optional[str] = self.telemetry_config.get("secret_key")

        self.server_url: str = os.environ.get("KIRA_TELEMETRY_SERVER", "https://telemetry.kira-ai.top/api/v1")
        self.heartbeat_interval: int = 300  # 5 minutes
        self._http_client: Optional[httpx.AsyncClient] = None
        self.country_code: Optional[str] = None
        self._send_queue: asyncio.Queue[TelemetryEvent] = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._stats_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def initialize(self) -> None:
        """Asynchronous initialization: ensure HTTP client and UUID are ready."""
        if not self.enabled:
            logger.info("Telemetry is disabled.")
            return

        # Use a transport with proxy=None to bypass HTTP_PROXY / HTTPS_PROXY env vars
        self._http_client = httpx.AsyncClient(timeout=30.0, transport=httpx.AsyncHTTPTransport(proxy=None))
        self._shutdown_event = asyncio.Event()

        if not self.client_uuid or not self.secret_key:
            await self._request_uuid()

        if self.client_uuid and self.secret_key:
            self.country_code = await self._fetch_country_code()
            self._worker_task = asyncio.create_task(self._send_worker())
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            self._stats_task = asyncio.create_task(self._stats_loop())
            self.send_system_startup()
            logger.info(f"Telemetry client initialized (UUID: {self.client_uuid}).")
        else:
            logger.warning("Telemetry client failed to acquire UUID; events will be dropped.")

    def _send_sync(self, event_type: str, data: dict[str, Any]) -> None:
        """Synchronous fire-and-forget send, immune to async task cancellation."""
        if not self.client_uuid or not self.secret_key:
            return
        payload = self._build_payload(event_type, data)
        payload["signature"] = self._sign_payload(payload)
        try:
            with httpx.Client(timeout=5.0, transport=httpx.HTTPTransport(proxy=None)) as client:
                client.post(f"{self.server_url}/events", json=payload).raise_for_status()
            logger.info(f"Sync event sent: {event_type}")
        except Exception as e:
            logger.warning(f"Failed to send sync event {event_type}: {e}")

    async def shutdown(self) -> None:
        """Graceful shutdown: flush pending events and close HTTP client."""
        try:
            # Final stats report before shutdown
            await self._report_stats()

            started_ts = self.stats.get_stats("started_ts") if self.stats else None
            if started_ts:
                uptime_ms = int((datetime.now(timezone.utc).timestamp() - started_ts) * 1000)
                self._send_sync(TelemetryEventType.SYSTEM_SHUTDOWN, {"uptime_duration_ms": uptime_ms})

            self._shutdown_event.set()

            for task in (self._heartbeat_task, self._worker_task, self._stats_task):
                if task and not task.done():
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass

            if self._http_client:
                await self._http_client.aclose()
                self._http_client = None

            logger.info("Telemetry client shut down.")
        except Exception as e:
            logger.warning(f"Telemetry shutdown error: {e}")

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
            self._http_client = httpx.AsyncClient(timeout=30.0, transport=httpx.AsyncHTTPTransport(proxy=None))

        if not self.client_uuid or not self.secret_key:
            await self._request_uuid()

        if not self.client_uuid or not self.secret_key:
            logger.error("Cannot reopen telemetry: failed to acquire UUID.")
            return False

        # Reset shutdown event so background workers can actually run
        self._shutdown_event = asyncio.Event()

        # Start background workers if they are not running
        if not self._worker_task or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._send_worker())
        if not self._heartbeat_task or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        if not self._stats_task or self._stats_task.done():
            self._stats_task = asyncio.create_task(self._stats_loop())

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

        update: dict[str, Any] = {
            "enabled": self.enabled,
            "client_uuid": self.client_uuid,
            "secret_key": self.secret_key,
        }
        self.config["telemetry"].update(update)
        self.config.save_config()

    def _build_payload(self, event_type: str, data: dict[str, Any]) -> dict[str, Any]:
        """Build an event payload dict (without signature)."""
        event = TelemetryEvent(
            event_type=event_type,
            data=data,
            client_uuid=self.client_uuid,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        return event.to_payload()

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
                logger.warning(f"Failed to send telemetry event: {type(e).__name__}: {e}")

    # ------------------------------------------------------------------
    # Geo lookup
    # ------------------------------------------------------------------
    async def _fetch_country_code(self) -> Optional[str]:
        """
        Fetch country code from public IP via ip-api.com.
        Uses a dedicated client with proxy explicitly disabled.
        """
        transport = httpx.AsyncHTTPTransport(proxy=None)
        try:
            async with httpx.AsyncClient(timeout=10.0, transport=transport) as client:
                resp = await client.get("http://ip-api.com/json/?fields=countryCode")
                resp.raise_for_status()
                code = resp.json().get("countryCode")
                if code:
                    self.country_code = code
                    logger.info(f"Country code detected: {code}")
                    return code
        except Exception as e:
            logger.warning(f"Failed to fetch country code: {e}")
        return None

    # ------------------------------------------------------------------
    # Convenience helpers for common events
    # ------------------------------------------------------------------
    def send_system_startup(self, python_version: str = "") -> None:
        data: dict[str, Any] = {
            "kira_ai_version": VERSION,
            "python_version": python_version or sys_platform.python_version(),
            "platform": sys_platform.platform(),
        }
        if self.country_code:
            data["country_code"] = self.country_code
        self.send_event(TelemetryEventType.SYSTEM_STARTUP, data)

    def send_system_shutdown(self, uptime_duration_ms: int) -> None:
        self.send_event(TelemetryEventType.SYSTEM_SHUTDOWN, {
            "uptime_duration_ms": uptime_duration_ms,
        })

    def send_heartbeat(self, uptime_ms: int, active_connections: int = 0) -> None:
        self.send_event(TelemetryEventType.HEARTBEAT, {
            "uptime_ms": uptime_ms,
            "active_connections": active_connections,
        })

    # ------------------------------------------------------------------
    # Hourly stats aggregation
    # ------------------------------------------------------------------
    async def _stats_loop(self) -> None:
        """Background loop that aggregates and reports telemetry data every 30 minutes."""
        while not self._shutdown_event.is_set():
            try:
                await asyncio.wait_for(self._shutdown_event.wait(), timeout=1800.0)
            except asyncio.TimeoutError:
                pass
            else:
                break

            await self._report_stats()

    async def _report_stats(self) -> None:
        """Aggregate unreported records, send to server, then mark as reported."""
        try:
            since_ts = int(time.time()) - 12 * 3600

            # Message stats — combine all platforms per hour into one event
            msg_rows = await self.db.get_unreported_telemetry_messages_by_hour(since_ts)
            if msg_rows:
                by_hour: dict[int, dict[str, int]] = {}
                for row in msg_rows:
                    hour = by_hour.setdefault(row["hour_ts"], {})
                    hour[row["platform"]] = hour.get(row["platform"], 0) + row["count"]
                for hour_ts, platforms in by_hour.items():
                    self.send_event(TelemetryEventType.MESSAGE_STATS, {
                        "hour": datetime.fromtimestamp(hour_ts, tz=timezone.utc).isoformat(),
                        "total_messages": sum(platforms.values()),
                        "messages_by_platform": platforms,
                        "time_window_minutes": 60,
                    })

            # LLM usage stats — one event per (hour, model)
            llm_rows = await self.db.get_unreported_telemetry_llm_usage_by_hour(since_ts)
            for row in llm_rows:
                avg_response = int(row["total_response_ms"] / row["call_count"]) if row["call_count"] else 0
                self.send_event(TelemetryEventType.LLM_USAGE, {
                    "hour": datetime.fromtimestamp(row["hour_ts"], tz=timezone.utc).isoformat(),
                    "model": row["model"],
                    "total_calls": row["call_count"],
                    "success_calls": row["success_count"],
                    "failed_calls": row["call_count"] - row["success_count"],
                    "total_input_tokens": row["total_input"],
                    "total_output_tokens": row["total_output"],
                    "total_cached_tokens": row["total_cached"],
                    "avg_response_time_ms": avg_response,
                })

            # Mark all as reported
            if msg_rows or llm_rows:
                await self.db.mark_telemetry_reported()
                logger.info(f"Hourly stats reported: {len(msg_rows)} message rows, {len(llm_rows)} LLM rows.")

            # Cleanup records older than 48 hours
            cutoff = int(time.time()) - 48 * 3600
            await self.db.delete_telemetry_records_before(cutoff)

        except Exception as e:
            logger.warning(f"Failed to report hourly stats: {e}")
