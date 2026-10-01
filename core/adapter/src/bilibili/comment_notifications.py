from __future__ import annotations

import asyncio
from dataclasses import dataclass
import time
from typing import TYPE_CHECKING, Any

from bilibili_api.utils.aid_bvid_transformer import bvid2aid

from core.adapter.feed import FeedItem, FeedRef
from core.chat import KiraCommentEvent, MessageChain
from core.chat.message_elements import Text

from .feed_content import COMMENT_RESOURCES

if TYPE_CHECKING:
    from .bilibili import BiliBiliAdapter


@dataclass
class _NotificationCursor:
    last_time: int
    last_id: int = 0


class BiliBiliCommentNotifications:
    """Receive account comment replies and mentions through SDK message feeds."""

    def __init__(self, adapter: BiliBiliAdapter):
        self.adapter = adapter
        self.reset()

    def reset(self) -> None:
        self._since_ts = int(time.time())
        self._video_cursor = (self._since_ts, 0)
        self._streams = {
            kind: _NotificationCursor(self._since_ts)
            for kind in ("reply", "at")
        }

    @staticmethod
    def _comment_key(event: KiraCommentEvent) -> tuple[str, str, str]:
        target = event.target
        if isinstance(target, FeedItem):
            target = target.comment_target or target.ref
        oid = target.id
        if target.resource_type == "video" and str(oid).startswith("BV"):
            oid = bvid2aid(str(oid))
        return target.resource_type, str(oid), str(event.comment_id)

    async def check(self) -> None:
        # Retain only this check's candidates, including older items from other sources.
        candidates: dict[tuple[str, str, str], KiraCommentEvent] = {}
        already_processed: set[tuple[str, str, str]] = set()
        checkpoints = {}

        def collect(event: KiraCommentEvent, is_new: bool) -> None:
            key = self._comment_key(event)
            if is_new:
                candidates.setdefault(key, event)
            else:
                already_processed.add(key)

        video_checkpoint = None
        if self.adapter.config.get("listening_bvid"):
            try:
                events = await self.adapter.feed.get_comment_events()
                video_checkpoint = self._video_cursor
                for event in events:
                    position = (event.timestamp, int(event.comment_id))
                    if event.timestamp > self._since_ts:
                        collect(event, position > self._video_cursor)
                    video_checkpoint = max(video_checkpoint, position)
            except Exception as exc:
                self.adapter.logger.warning(f"Bilibili video comment polling failed: {type(exc).__name__}")

        for kind, state in self._streams.items():
            try:
                events, checkpoint = await asyncio.wait_for(self._check_stream(kind, state), timeout=60.0)
                for event, is_new in events:
                    collect(event, is_new)
                checkpoints[kind] = checkpoint
            except Exception as exc:
                # SDK exceptions can contain private response bodies.
                self.adapter.logger.warning(
                    f"Bilibili {kind} comment notification polling failed: {type(exc).__name__}"
                )

        interval = max(0.0, float(self.adapter.config.get("message_process_interval", 5.0) or 0))
        for key, event in sorted(candidates.items(), key=lambda pair: pair[1].timestamp):
            if key not in already_processed:
                self.adapter.feed.publish(event)
                await asyncio.sleep(interval)
        for kind, (timestamp, notification_id) in checkpoints.items():
            self._streams[kind] = _NotificationCursor(timestamp, notification_id)
        if video_checkpoint is not None:
            self._video_cursor = video_checkpoint
            self.adapter.feed.last_process_ts = video_checkpoint[0]

    async def _check_stream(
        self, kind: str, state: _NotificationCursor,
    ) -> tuple[list[tuple[KiraCommentEvent, bool]], tuple[int, int]]:
        client = self.adapter.get_client()
        fetch = client.get_reply_notifications if kind == "reply" else client.get_at_notifications
        boundary = (state.last_time, state.last_id)
        newest = boundary
        events = []
        cursor = None
        visited = set()
        # Complete the batch before publishing; a failed page leaves the cursor unchanged.
        for _ in range(100):
            page = await fetch(
                cursor_id=cursor[0] if cursor else None,
                cursor_time=cursor[1] if cursor else None,
            )
            items = page.get("items") or []
            reached_boundary = False
            for notification in reversed(items):
                try:
                    timestamp = int(notification.get(f"{kind}_time") or 0)
                    notification_id = int(notification["id"])
                    if timestamp <= 0 or notification_id <= 0:
                        raise ValueError("Invalid notification cursor")
                    position = (timestamp, notification_id)
                    is_new = timestamp > self._since_ts and position > boundary
                    reached_boundary |= not is_new
                    newest = max(newest, position)
                    event = self._event(notification, kind, timestamp)
                except (KeyError, TypeError, ValueError, AttributeError):
                    self.adapter.logger.warning(f"Bilibili {kind} comment notification skipped: invalid metadata")
                    continue
                if event is not None and timestamp > self._since_ts:
                    events.append((event, is_new))
            next_cursor = page.get("cursor") or {}
            if not items or reached_boundary or next_cursor.get("is_end", True):
                return events, newest
            cursor = (int(next_cursor["id"]), int(next_cursor["time"]))
            if cursor in visited:
                raise ValueError("Repeated Bilibili notification cursor")
            visited.add(cursor)
        raise ValueError("Bilibili notification pagination budget exceeded")

    def _event(self, notification: dict[str, Any], kind: str, timestamp: int) -> KiraCommentEvent | None:
        item = notification.get("item") or {}
        sender = notification.get("user") or {}
        uid = str(sender.get("mid") or "")
        if not uid or uid == str(self.adapter.bot_uid):
            return None
        # Mentions of a post or danmaku must not become comment replies.
        if kind == "at" and item.get("type") != "reply":
            return None
        if item.get("type") not in {"reply", "video", "dynamic", "article", "audio"}:
            return None
        resource_type = COMMENT_RESOURCES.get(int(item.get("business_id") or 0))
        oid = int(item.get("subject_id") or 0)
        comment_id = int(item.get("source_id") or 0)
        text = item.get("source_content")
        if resource_type is None or oid <= 0 or comment_id <= 0 or not isinstance(text, str) or not text.strip():
            return None
        root_id = int(item["root_id"] or 0) or comment_id
        if root_id <= 0:
            return None
        resource = FeedRef(resource_type, str(oid))
        target: FeedItem | FeedRef = resource
        if resource_type == "dynamic":
            # This ID already identifies the native comment resource, not a dynamic lookup.
            target = FeedItem(
                ref=resource, kind="post", content=MessageChain(),
                comment_target=resource, title=item.get("title"), url=item.get("uri"),
            )
        root_text = item.get("root_reply_content")
        # The default comment plugin treats root context as the bot's own words.
        own_root = kind == "reply" and root_id != comment_id and root_id == int(item.get("target_id") or 0)
        return KiraCommentEvent(
            platform=self.adapter.info.platform,
            adapter_name=self.adapter.info.name,
            commenter_id=uid,
            commenter_nickname=sender.get("nickname") or uid,
            self_id=self.adapter.bot_uid,
            timestamp=timestamp,
            comment_id=comment_id,
            comment_content=MessageChain([Text(text)]),
            target=target,
            root_comment_id=root_id,
            root_comment_content=MessageChain([Text(root_text)]) if own_root and root_text else None,
        )
