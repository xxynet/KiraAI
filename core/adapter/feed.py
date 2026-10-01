from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from core.chat.message_utils import MessageChain


class FeedKind(str, Enum):
    """Common content kinds; adapters may also use custom strings."""

    POST = "post"
    VIDEO = "video"
    ARTICLE = "article"
    AUDIO = "audio"
    UNKNOWN = "unknown"

    def __str__(self) -> str:
        return self.value


class FeedSource(str, Enum):
    """Common feed sources; adapters may also use custom strings."""

    RECOMMENDED = "recommended"
    FOLLOWING = "following"
    USER = "user"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class FeedRef:
    """An opaque resource reference interpreted by the selected adapter."""

    resource_type: str
    id: str | int


@dataclass
class FeedAuthor:
    id: str | None = None
    name: str | None = None


@dataclass
class FeedAttachment:
    """An attachment or linked resource; video URLs may be viewing pages."""

    kind: Literal["image", "video", "audio", "link"]
    url: str | None = None
    ref: FeedRef | None = None
    title: str | None = None
    cover_url: str | None = None
    width: int | None = None
    height: int | None = None
    duration: float | None = None


@dataclass
class FeedItem:
    ref: FeedRef
    kind: FeedKind | str
    content: MessageChain
    author: FeedAuthor = field(default_factory=FeedAuthor)
    title: str | None = None
    attachments: list[FeedAttachment] = field(default_factory=list)
    published_at: datetime | None = None
    url: str | None = None
    cover_url: str | None = None
    duration: float | None = None
    stats: dict[str, int | str] = field(default_factory=dict)
    linked_content: FeedRef | None = None
    comment_target: FeedRef | None = None
    original: FeedItem | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FeedQuery:
    """Browse a feed with common filters and adapter-specific ``extra`` options.

    Continuation cursors belong to the issuing adapter instance.
    """

    source: FeedSource | str = FeedSource.RECOMMENDED
    count: int = 20
    kinds: tuple[FeedKind | str, ...] = ()
    author_id: str | int | None = None
    cursor: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FeedSearchQuery:
    """Search with optional keywords, author, and adapter-specific filters.

    Each adapter decides which combinations of filters it supports.
    """

    keyword: str | None = None
    kind: FeedKind | str = FeedKind.VIDEO
    count: int = 20
    cursor: str | None = None
    author_id: str | int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class FeedPage:
    items: list[FeedItem] = field(default_factory=list)
    next_cursor: str | None = None
    has_more: bool = False


@dataclass
class FeedPost:
    """Content and platform-specific publishing options for one account.

    ``extra`` is interpreted by the concrete capability and must not override
    the adapter's account credentials.
    """

    content: MessageChain
    extra: dict[str, Any] = field(default_factory=dict)
