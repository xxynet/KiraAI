"""Scoped memory with lexical search, optional remote embeddings and reranking."""

import asyncio
from functools import partial, wraps
import json

from core.plugin import BasePlugin, PageMenu, PluginPage, logger, on, register
from core.provider import LLMRequest
from core.utils.path_utils import get_data_path

from . import webui
from .prompts import MESSAGES
from .scope import MemoryInputError, MemoryScope
from .store import MemoryStore
from .search import MAX_CANDIDATES, fuse
from .vector import VectorMemory
from .rerank import MemoryReranker


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
        self.vectors = VectorMemory(self.store, ctx, cfg)
        self.reranker = MemoryReranker(ctx, cfg)

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
        self.vectors.start()
        if count:
            logger.info("Imported %d legacy memories with shared visibility; original and backup retained", count)

    async def terminate(self):
        self._ready = False
        await self.vectors.close()

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
        if added:
            self.vectors.changed()
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
            rows = await self.search(scope, query, limit=limit, kind=kind, owner_type=owner_type,
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
        await self.vectors.updated(memory_id)
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
        self.vectors.changed()
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

    async def search(self, scope, query="", **options):
        return await self._hybrid_search(*self.store._visible(scope), query=query, **options)

    async def search_preview(self, query="", *, persona_id=None, session_id=None, **options):
        return await self._hybrid_search(
            *self.store.preview_predicate(persona_id, session_id), query=query, **options,
        )

    async def _hybrid_search(self, predicate, params, query="", *, limit=8, offset=0,
                             rerank_report=None, **options):
        lexical = await self.store._search(
            predicate, params, query, limit=limit, offset=offset, **options,
        )
        if rerank_report is not None:
            rerank_report.update(self.reranker.report("disabled" if not self.reranker.enabled else "skipped"))
        if not query.strip() or options.get("core_only"):
            return lexical
        combined = None
        if self.vectors.enabled:
            filtered, values = self.store.search_filter(predicate, params, **options)
            semantic = await self.vectors.search(query, filtered, values)
            if semantic:
                # A fixed candidate pool keeps paging stable and applies scope before ranking.
                candidates = await self.store._search(
                    predicate, params, query, limit=MAX_CANDIDATES, candidate_pool=True, **options,
                )
                combined = await asyncio.to_thread(fuse, candidates, semantic)
        # Rerank only a fixed prefix, so pagination never reranks individual pages independently.
        if self.reranker.enabled and offset < self.reranker.candidate_limit:
            if combined is None:
                combined = await self.store._search(
                    predicate, params, query, limit=max(self.reranker.candidate_limit, offset + limit),
                    candidate_pool=True, **options,
                )
            combined, report = await self.reranker.rank(query, combined)
            if rerank_report is not None:
                rerank_report.update(report)
        return combined[offset:offset + limit] if combined is not None else lexical

    async def recall(self, scope, messages):
        """Build the scoped memory payload used by actual conversations."""
        return await self._recall(partial(self.search, scope), messages)

    async def _recall(self, search, messages):
        """Share ranking, deduplication and budgets across recall entry points."""
        core_limit = self.setting("core_limit", 10, 1, 20)
        recall_limit = self.setting("recall_limit", 6, 1, 20)
        budget = self.setting("prompt_char_budget", 6000, 1500, 20000)
        core = await search(core_only=True, limit=core_limit)
        query = " ".join(str(message or "")[:160] for message in messages[-3:])[:512]
        rerank_report = self.reranker.report("disabled" if not self.reranker.enabled else "skipped")
        recalled = await search(query, limit=recall_limit, rerank_report=rerank_report) if query.strip() else []
        core_records = self.pack(core, budget // 2)
        core_ids = {record["id"] for record in core_records}
        recalled_records = self.pack([row for row in recalled if row["id"] not in core_ids], budget // 2)
        return {
            "query": query,
            "retrieval": {"mode": "hybrid" if self.vectors.enabled and self.vectors.ready else "keyword",
                          "phase": self.vectors.phase, "reason": self.vectors.reason, "rerank": rerank_report},
            "core": core_records,
            "recalled": recalled_records,
            "prompt_chars": len(self.encode(core_records + recalled_records)),
            "limits": {"core": core_limit, "recall": recall_limit, "prompt_chars": budget},
        }

    @on.llm_request()
    async def inject_memory(self, event, req: LLMRequest, *_):
        try:
            persona_id = next((p.kwargs.get("persona_id") for p in req.system_prompt if p.name == "memory"), None)
            scope = await self.scope(event, persona_id)
            recalled = await self.recall(scope, [
                getattr(message, "message_str", "")
                for message in event.messages[-3:] if not getattr(message, "is_notice", False)
            ])
            records = recalled["core"] + recalled["recalled"]
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

    # ------------------------------------------------------------------
    # Maintenance page (WebUI) and its authenticated operator API.
    #
    # The page is mounted on a non-empty sub-path: a root mount is stored by
    # Starlette without a trailing slash, which the host's page cleanup cannot
    # match after a hot reload, leaving a stale mount that shadows the
    # re-registered route.
    # ------------------------------------------------------------------

    @register.page(
        "/dashboard",
        menu=PageMenu(
            label={"zh": "记忆管理", "en": "Memory"},
            icon="Coin",
            order=85,
        ),
    )
    def memory_page(self):
        return PluginPage.from_folder("./web")

    async def _admin(self, call):
        """Run a store call, mapping typed input failures onto HTTP 400.

        The error code is a stable identifier the page translates; no memory
        content ever appears in the detail.
        """
        from fastapi import HTTPException

        if not self._ready:
            raise HTTPException(status_code=503, detail="memory_unavailable")
        try:
            return await call()
        except MemoryInputError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @register.api(method="GET", path="/memory/overview")
    async def api_overview(self):
        async def load():
            data = await self.store.overview()
            return webui.overview_payload(
                data,
                max_core=self.setting("core_limit", 10, 1, 20),
                max_recall=self.setting("recall_limit", 6, 1, 20),
            )

        return await self._admin(load)

    @register.api(method="GET", path="/memory/records")
    async def api_records(self, q: str = "", kind: str = "", status: str = "", owner_type: str = "",
                          origin: str = "", core: str = "", page: str = "", size: str = ""):
        async def load():
            filters = webui.parse_filters({
                "q": q, "kind": kind, "status": status, "owner_type": owner_type,
                "origin": origin, "core": core,
            })
            page_number = webui.parse_page(page, 1, 1, 100000)
            page_size = webui.parse_page(size, 20, 1, 100)
            result = await self.store.admin_list(page=page_number, size=page_size, **filters)
            return {
                "items": [webui.serialize(row) for row in result["items"]],
                "total": result["total"],
                "page": result["page"],
                "size": result["size"],
            }

        return await self._admin(load)

    @register.api(method="GET", path="/memory/records/{memory_id}")
    async def api_record_detail(self, memory_id: str):
        async def load():
            row = await self.store.admin_get(memory_id)
            if row is None:
                raise MemoryInputError("not_found")
            return webui.serialize(row) | {"terms": row.get("terms", 0)}

        return await self._admin(load)

    @register.api(method="POST", path="/memory/records/{memory_id}")
    async def api_record_update(self, memory_id: str, payload: dict):
        async def save():
            row = await self.store.admin_update(memory_id, **webui.parse_update(payload))
            await self.vectors.updated(memory_id)
            return webui.serialize(row) | {"terms": row["terms"]}

        return await self._admin(save)

    @register.api(method="DELETE", path="/memory/records/{memory_id}")
    async def api_record_remove(self, memory_id: str, revision: int):
        async def remove():
            await self.store.admin_remove(memory_id, revision)
            self.vectors.changed()
            return {"ok": True, "memory_id": memory_id}

        return await self._admin(remove)

    @register.api(method="GET", path="/memory/facets")
    async def api_facets(self):
        return await self._admin(self.store.facets)

    @register.api(method="GET", path="/memory/recall-options")
    async def api_recall_options(self):
        async def load():
            stored = await self.store.facets()
            personas = {item.id: {"id": item.id, "name": item.name or item.id}
                        for item in await self.ctx.persona_mgr.list_personas()}
            for persona_id in stored["personas"]:
                personas.setdefault(persona_id, {"id": persona_id, "name": persona_id})
            active = await self.ctx.persona_mgr.get_persona()
            if active:
                personas.setdefault(active.id, {"id": active.id, "name": active.name or active.id})
            sessions = {item.sid: {"id": item.sid, "name": item.session_title or item.sid}
                        for item in await self.ctx.session_mgr.get_sessions(include_content=False)}
            for item in await self.ctx.message_history.list_sessions():
                sessions.setdefault(item.session_id, {"id": item.session_id, "name": item.session_id})
            for item in stored["contexts"]:
                sid = item["session_id"]
                sessions.setdefault(sid, {"id": sid, "name": sid})
            return {
                "personas": list(personas.values()),
                "active_persona": active.id if active else None,
                "sessions": [item for sid, item in sessions.items()
                             if len(sid.split(":", 2)) == 3 and sid.split(":", 2)[1] in {"dm", "gm"}],
            }
        return await self._admin(load)

    @register.api(method="GET", path="/memory/recall-context")
    async def api_recall_context(self, session_id: str):
        async def load():
            parts = session_id.split(":", 2)
            if len(session_id) > 512 or len(parts) != 3 or parts[1] not in {"dm", "gm"} or not parts[0] or not parts[2]:
                raise MemoryInputError("invalid_recall")
            page = await self.ctx.message_history.get_messages(session_id=session_id, direction="incoming", limit=50)
            messages = [message for message in page.messages if not message.is_notice]
            speakers = {}
            for message in messages:
                if message.sender_id and message.sender_id != "unknown":
                    uid = str(message.sender_id)
                    speakers.setdefault(uid, {"id": uid, "name": message.sender_name or uid})
            for uid in await self.store.recall_users(session_id):
                speakers.setdefault(uid, {"id": uid, "name": uid})
            return {
                "session_id": session_id, "adapter": parts[0], "group": parts[1] == "gm",
                "speakers": list(speakers.values()) if parts[1] == "gm" else [],
                "default_user_ids": ([parts[2]] if parts[1] == "dm" else list(speakers)[:1]),
            }
        return await self._admin(load)

    @register.api(method="POST", path="/memory/recall")
    async def api_recall(self, payload: dict):
        async def load():
            if "adapter" in payload:
                scope, messages = webui.parse_recall(payload)
                return await self.recall(scope, messages)
            filters, messages = webui.parse_recall_preview(payload)
            return await self._recall(partial(self.search_preview, **filters), messages)

        return await self._admin(load)

    @register.api(method="GET", path="/memory/vector/status")
    async def api_vector_status(self):
        return await self._admin(self.vectors.status)

    @register.api(method="POST", path="/memory/vector/install")
    async def api_vector_install(self):
        return await self._admin(self.vectors.install)

    @register.api(method="POST", path="/memory/vector/rebuild")
    async def api_vector_rebuild(self):
        return await self._admin(self.vectors.rebuild)

    @register.api(method="GET", path="/memory/config")
    async def api_config(self):
        """Effective settings for the page.

        The editable fields themselves are rendered by the host plugin
        configuration form from ``schema.json``; this endpoint only exposes the
        clamped runtime values actually in force.
        """
        return {
            "values": {
                "core_limit": self.setting("core_limit", 10, 1, 20),
                "recall_limit": self.setting("recall_limit", 6, 1, 20),
                "prompt_char_budget": self.setting("prompt_char_budget", 6000, 1500, 20000),
                "search_char_budget": self.setting("search_char_budget", 12000, 5000, 30000),
            },
            "defaults": {
                "core_limit": 10,
                "recall_limit": 6,
                "prompt_char_budget": 6000,
                "search_char_budget": 12000,
            },
            "ready": self._ready,
            "database": str(self.store.path),
        }
