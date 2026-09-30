"""Plugin store catalog retrieval, caching, and entry normalization."""

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Union
from uuid import uuid4

from pydantic import BaseModel, Field

from core.logging_manager import get_logger
from core.utils.network import get_json
from core.utils.path_utils import get_data_path

logger = get_logger("plugin_store", "cyan")
CACHE_TTL_SECONDS = 600


@dataclass(frozen=True)
class StoreSource:
    """An immutable source snapshot; persisted changes remain owned by the database."""

    url: str
    id: Optional[str] = None
    name: str = ""
    cache_file: Optional[str] = None
    updated_at: int = 0
    is_current: bool = False
    created_at: int = 0

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "StoreSource":
        return cls(
            url=record["url"],
            id=record["id"],
            name=record.get("name", ""),
            cache_file=record.get("cache_file"),
            updated_at=record.get("updated_at", 0),
            is_current=record.get("is_current", False),
            created_at=record.get("created_at", 0),
        )


class PluginStoreItemResponse(BaseModel):
    id: str
    name: str
    version: str = ""
    author: str = ""
    description: str = ""
    category: Optional[str] = None
    category_name: Optional[str] = None
    category_locales: Dict[str, Dict[str, str]] = Field(default_factory=dict)
    repo: Optional[str] = None
    commit_sha: Optional[str] = None
    release_tag: Optional[str] = None
    icon: Optional[str] = None
    icon_dark: Optional[str] = None
    locales: Dict[str, Dict[str, str]] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)
    core_version: Optional[str] = None
    stars: int = 0
    updated_at: Optional[Union[int, str]] = None


@dataclass
class StoreFetchResult:
    data: Any
    cache_file: Optional[str] = None
    updated_at: Optional[int] = None
    fetch_error: Optional[Exception] = None


class PluginStore:
    """Retrieve and cache a catalog bound to one immutable source snapshot."""

    def __init__(self, source: StoreSource, cache_dir: Optional[Path] = None):
        self.source = source
        self.cache_dir = cache_dir if cache_dir is not None else get_data_path() / "plugin_src"

    async def read_cache(self, *, strict: bool = False) -> Optional[Any]:
        return await asyncio.to_thread(self._read_cache, self.source.cache_file, strict)

    def _read_cache(self, cache_file: Optional[str], strict: bool) -> Optional[Any]:
        if not cache_file:
            return None
        cache_path = self.cache_dir / cache_file
        if not cache_path.exists():
            return None
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as error:
            if strict:
                raise
            logger.warning(f"Failed to read plugin store cache {cache_path}: {error}")
            return None

    def _write_cache(self, data: Any, existing_filename: Optional[str]) -> str:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        if existing_filename and (self.cache_dir / existing_filename).exists():
            filename = existing_filename
        else:
            filename = f"plugins_{uuid4().hex}.json"
        (self.cache_dir / filename).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return filename

    async def fetch(
        self,
        *,
        force_refresh: bool = False,
        persist_cache: bool = False,
        allow_cache_fallback: bool = False,
        strict_cache: bool = False,
    ) -> StoreFetchResult:
        """Fetch a catalog while preserving the caller's cache and failure policy.

        Browsing permits stale-cache fallback; update checks propagate failures
        and reject corrupt fresh caches. Only successful persisted responses
        return new cache metadata for the caller to save.
        """
        if (
            not force_refresh
            and self.source.cache_file
            and int(time.time()) - self.source.updated_at < CACHE_TTL_SECONDS
        ):
            data = await self.read_cache(strict=strict_cache)
            if data is not None:
                return StoreFetchResult(data)

        try:
            data = await get_json(self.source.url, timeout=15.0)
        except Exception as error:
            if not allow_cache_fallback:
                raise
            data = await self.read_cache()
            if data is None:
                raise
            logger.warning(
                "Failed to refresh plugin store %s; using local cache: %s", self.source.url, error
            )
            return StoreFetchResult(data, fetch_error=error)

        result = StoreFetchResult(data)
        if persist_cache:
            result.cache_file = await asyncio.to_thread(self._write_cache, data, self.source.cache_file)
            result.updated_at = int(time.time())
        return result

    async def refresh_cache(self) -> Optional[str]:
        """Refresh a source cache without failing source creation or selection."""
        try:
            result = await self.fetch(force_refresh=True, persist_cache=True)
            return result.cache_file
        except Exception as error:
            logger.warning(f"Failed to fetch/cache plugin store data from {self.source.url}: {error}")
            return None

    async def delete_cache(self) -> None:
        if self.source.cache_file:
            await asyncio.to_thread(self._delete_cache, self.source.cache_file)

    def _delete_cache(self, cache_file: str) -> None:
        cache_path = self.cache_dir / cache_file
        try:
            if cache_path.exists():
                cache_path.unlink()
        except Exception as error:
            logger.warning(f"Failed to delete cache file {cache_path}: {error}")


def extract_plugins(raw_data: Any) -> List[PluginStoreItemResponse]:
    """Extract and normalize plugin entries from raw store JSON.

    Supports the standard format ``{\"plugins\": {\"<id>\": {...}, ...}}``
    as well as a plain array of plugin objects.

    Standard schema fields prioritized:
      plugin_id, display_name, version, author, description

    Extra useful fields (if present): category, repo, stars, updated_at, name, id

    GitHub metadata is limited to the public star count used for sorting.
    """
    raw_plugins: Any = None
    category_catalog: Dict[str, Any] = {}
    if isinstance(raw_data, dict):
        raw_plugins = raw_data.get("plugins", [])
        raw_categories = raw_data.get("categories")
        if isinstance(raw_categories, dict):
            category_catalog = raw_categories
    elif isinstance(raw_data, list):
        raw_plugins = raw_data

    if not isinstance(raw_plugins, (dict, list)):
        return []

    if isinstance(raw_plugins, dict):
        plugin_list = list(raw_plugins.values())
    else:
        plugin_list = list(raw_plugins)

    result: List[PluginStoreItemResponse] = []
    for raw in plugin_list:
        if not isinstance(raw, dict):
            continue

        plugin_id = raw.get("plugin_id") or raw.get("id") or raw.get("name", "")
        display_name = raw.get("display_name") or raw.get("name") or str(plugin_id)
        version = raw.get("version")
        author = raw.get("author", "")
        description = raw.get("description", "")
        category = raw.get("category")
        category_info = category_catalog.get(category) if isinstance(category, str) else None
        category_name = category_info.get("name") if isinstance(category_info, dict) else None
        category_locales = category_info.get("locales") if isinstance(category_info, dict) else None
        repo = raw.get("repo") or raw.get("repo_url")
        raw_commit_sha = raw.get("commit_sha")
        if raw_commit_sha is None:
            commit_sha = None
        elif isinstance(raw_commit_sha, str):
            normalized_commit_sha = raw_commit_sha.strip().lower()
            if len(normalized_commit_sha) == 40 and all(
                character in "0123456789abcdef" for character in normalized_commit_sha
            ):
                commit_sha = normalized_commit_sha
            else:
                commit_sha = None
        else:
            commit_sha = None
        release_tag = raw.get("release_tag")
        icon = raw.get("icon")
        icon_dark = raw.get("icon_dark") or raw.get("icon-dark")
        github_data = raw.get("github_data")
        github_stars = github_data.get("stars", 0) if isinstance(github_data, dict) else 0
        stars = raw.get("stars", raw.get("star_count", github_stars))
        updated_at = raw.get("updated_at", raw.get("updatedAt"))

        locales = raw.get("locales")
        tags = raw.get("tags")
        core_version = raw.get("core_version")

        result.append(PluginStoreItemResponse(
            id=str(plugin_id),
            name=str(display_name),
            version=str(version) if version else "",
            author=str(author),
            description=str(description),
            category=str(category) if category else None,
            category_name=str(category_name) if category_name else None,
            category_locales=category_locales if isinstance(category_locales, dict) else {},
            repo=str(repo) if repo else None,
            commit_sha=commit_sha,
            release_tag=str(release_tag) if isinstance(release_tag, str) else None,
            icon=str(icon) if isinstance(icon, str) else None,
            icon_dark=str(icon_dark) if isinstance(icon_dark, str) else None,
            locales=locales if isinstance(locales, dict) else {},
            tags=[str(tag) for tag in tags if tag] if isinstance(tags, list) else [],
            core_version=str(core_version) if core_version else None,
            stars=int(stars) if isinstance(stars, (int, float, str)) and str(stars).isdigit() else 0,
            updated_at=updated_at if isinstance(updated_at, (int, str)) else None,
        ))

    return result
