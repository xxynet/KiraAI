"""Scoped long-term memory with local multilingual lexical retrieval."""

from functools import wraps
import json

from core.plugin import BasePlugin, logger, on, register
from core.provider import LLMRequest
from core.utils.path_utils import get_data_path

from .prompts import MESSAGES
from .scope import MemoryInputError, MemoryScope
from .store import MemoryStore


def guarded(func):
    @wraps(func)
    async def call(self, *args, **kwargs):
        try:
            return await func(self, *args, **kwargs)
        except MemoryInputError as exc:
            return self.result(False, str(exc))
        except (TypeError, ValueError):
            return self.result(False, "invalid_arguments")
        except Exception as exc:
            logger.warning("Memory operation failed (%s)", type(exc).__name__)
            return self.result(False, "unavailable")
    return call


TEXT = {"type": "string", "minLength": 1, "maxLength": 4000}
ID = {"type": "string", "description": "Stable memory ID returned by memory_search; never a line number."}
REVISION = {"type": "integer", "minimum": 1}
SOURCE = {"type": "string", "description": "Source message ID from this batch; required when multiple users speak."}
KIND = {"type": "string", "enum": ["semantic", "episodic", "procedural"]}
OWNER = {"type": "string", "enum": ["user", "group", "self"]}
STATUS = {"type": "string", "enum": ["active", "completed", "cancelled", "superseded"]}
PRIORITY = {"type": "integer", "minimum": 1, "maximum": 5}


def schema(properties, required=()):
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


class MemoryPlugin(BasePlugin):
    def __init__(self, ctx, cfg: dict):
        super().__init__(ctx, cfg)
        self.store = MemoryStore(get_data_path() / "memory" / "memories.db")
        self._ready = False

    @property
    def messages(self):
        return MESSAGES["zh" if (self.ctx.get_lang() or "en").startswith("zh") else "en"]

    def result(self, success, code="ok", **values):
        return json.dumps({"ok": success, "message": self.messages[code], **values}, ensure_ascii=False)

    def setting(self, key, default, minimum, maximum):
        value = self.plugin_cfg.get(key, default)
        if type(value) is not int:
            return default
        return max(minimum, min(maximum, value))

    async def initialize(self):
        count = await self.store.initialize(get_data_path() / "memory" / "core.txt")
        self._ready = True
        if count:
            logger.info("Imported %d legacy memories with shared visibility; original and backup retained", count)

    async def terminate(self):
        self._ready = False

    async def scope(self, event, persona_id=None):
        if not self._ready:
            raise MemoryInputError("unavailable")
        extra = getattr(event, "extra", None)
        if extra is None:
            event.extra = extra = {}
        cached = extra.get("_builtin_memory_scope")
        if isinstance(cached, MemoryScope):
            return cached
        if persona_id is None:
            persona = await self.ctx.persona_mgr.get_persona()
            persona_id = getattr(persona, "id", None)
        scope = MemoryScope.from_event(event, persona_id)
        extra["_builtin_memory_scope"] = scope
        return scope

    @register.tool(
        name="memory_add",
        description="Remember a fact, experience or explicit interaction agreement in the source language.",
        params=schema(
            {
                "text": TEXT,
                "owner_type": OWNER,
                "user_id": {
                    "type": "string",
                    "description": "Current speaker's exact ID; required for multi-user batches.",
                },
                "source_message_id": SOURCE,
                "kind": KIND,
                "importance": PRIORITY,
                "core": {
                    "type": "boolean",
                },
                "expires_at": {
                    "type": "number",
                },
            },
            [
                "text",
            ],
        ),
    )
    @guarded
    async def memory_add(self, event, text, owner_type="user", user_id=None, source_message_id=None,
                         kind="semantic", importance=3, core=False, expires_at=None):
        row, added = await self.store.add(
            await self.scope(event), text=text, owner_type=owner_type, user_id=user_id,
            source_message_id=source_message_id, kind=kind, importance=importance, core=core, expires_at=expires_at,
        )
        return self.result(True, "ok" if added else "duplicate", memory_id=row["id"], revision=row["revision"])

    @register.tool(
        name="memory_search",
        description=(
            "Search visible memories using source-language keywords; empty query lists records. "
            "Use memory_id for a single record."
        ),
        params=schema(
            {
                "query": {
                    "type": "string",
                    "maxLength": 512,
                },
                "memory_id": ID,
                "kind": KIND,
                "owner_type": {
                    "type": "string",
                    "enum": [
                        "user",
                        "group",
                        "self",
                        "legacy",
                    ],
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                },
                "offset": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 10000,
                },
                "include_inactive": {
                    "type": "boolean",
                },
            },
        ),
    )
    @guarded
    async def memory_search(self, event, query="", memory_id=None, kind=None, owner_type=None,
                            limit=8, offset=0, include_inactive=False):
        scope = await self.scope(event)
        if type(include_inactive) is not bool:
            raise MemoryInputError("invalid_arguments")
        if memory_id is not None:
            row = await self.store.get(scope, memory_id)
            if row is None:
                raise MemoryInputError("not_found")
            rows = [row]
        else:
            rows = await self.store.search(scope, query, limit=limit, kind=kind, owner_type=owner_type,
                                           include_inactive=include_inactive, offset=offset)
        records = self.pack(rows, self.setting("search_char_budget", 12000, 5000, 30000))
        return self.result(True, records=records, next_offset=offset + len(records) if records and memory_id is None else None)

    @register.tool(
        name="memory_update",
        description="Update a visible memory using its stable ID and current revision. Re-read on conflict.",
        params=schema(
            {
                "memory_id": ID,
                "revision": REVISION,
                "text": TEXT,
                "kind": KIND,
                "importance": PRIORITY,
                "core": {
                    "type": "boolean",
                },
                "status": STATUS,
                "expires_at": {
                    "type": "number",
                },
                "clear_expiry": {
                    "type": "boolean",
                },
                "source_message_id": SOURCE,
            },
            [
                "memory_id",
                "revision",
                "text",
            ],
        ),
    )
    @guarded
    async def memory_update(self, event, memory_id, revision, text, kind=None, importance=None,
                            core=None, status=None, expires_at=None, clear_expiry=False, source_message_id=None):
        if type(clear_expiry) is not bool:
            raise MemoryInputError("invalid_arguments")
        version = await self.store.update(
            await self.scope(event), memory_id, revision, text=text, kind=kind, importance=importance,
            core=core, status=status, expires_at=expires_at, clear_expiry=clear_expiry,
            source_message_id=source_message_id,
        )
        return self.result(True, memory_id=memory_id, revision=version)

    @register.tool(
        name="memory_remove",
        description="Delete a visible memory and its search index using stable ID and current revision.",
        params=schema(
            {
                "memory_id": ID,
                "revision": REVISION,
                "source_message_id": SOURCE,
            },
            [
                "memory_id",
                "revision",
            ],
        ),
    )
    @guarded
    async def memory_remove(self, event, memory_id, revision, source_message_id=None):
        await self.store.remove(await self.scope(event), memory_id, revision, source_message_id)
        return self.result(True, memory_id=memory_id)

    @staticmethod
    def encode(value):
        return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")

    @classmethod
    def pack(cls, rows, budget):
        records = []
        used = 2
        for row in rows:
            record = {key: row[key] for key in (
                "id", "revision", "text", "kind", "owner_type", "owner_id", "status", "core",
                "source_message_id", "created_at", "updated_at", "expires_at",
            )}
            encoded = cls.encode(record)
            if used + len(encoded) + 2 > budget:
                # Only truncate a single oversized record, never a normal page boundary.
                if records:
                    break
                available = max(0, budget - len(encoded) + len(record["text"]) - 80)
                record["text"] = record["text"][:available]
                record["truncated"] = True
                while len(cls.encode(record)) + 4 > budget and record["text"]:
                    record["text"] = record["text"][:len(record["text"]) // 2]
                if len(cls.encode(record)) + 4 > budget:
                    break
            records.append(record)
            used += len(cls.encode(record)) + 2
        return records

    @on.llm_request()
    async def inject_memory(self, event, req: LLMRequest, *_):
        try:
            persona_id = next((p.kwargs.get("persona_id") for p in req.system_prompt if p.name == "memory"), None)
            scope = await self.scope(event, persona_id)
            core = await self.store.search(scope, core_only=True, limit=self.setting("core_limit", 4, 1, 20))
            query = " ".join(
                str(getattr(message, "message_str", "") or "")[:160]
                for message in event.messages[-3:] if not getattr(message, "is_notice", False)
            )[:512]
            recalled = await self.store.search(scope, query, limit=self.setting("recall_limit", 6, 1, 20)) if query.strip() else []
            budget = self.setting("prompt_char_budget", 6000, 1500, 20000)
            core_records = self.pack(core, budget // 2)
            core_ids = {record["id"] for record in core_records}
            records = core_records + self.pack([row for row in recalled if row["id"] not in core_ids], budget // 2)
            context = {"persona_id": scope.persona_id, "session_id": scope.session_id,
                       "sources": [{"source_message_id": mid, "user_id": uid} for mid, uid in scope.sources[-30:]]}
            for prompt in req.system_prompt:
                if prompt.name == "memory":
                    # JSON escaping keeps stored tag-like text inside data boundaries.
                    payload = self.encode(records)
                    prompt.content += self.messages["rules"] + "\n" + payload
                elif prompt.name == "tools":
                    prompt.content += self.messages["tools"] + "\n" + self.encode(context)
        except MemoryInputError:
            return
        except Exception as exc:
            logger.warning("Memory recall unavailable (%s)", type(exc).__name__)
