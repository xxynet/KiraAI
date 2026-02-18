"""
向量数据库存储层，使用 ChromaDB 实现长期记忆的向量检索
"""
import inspect
import os
import threading
import time
import uuid
from typing import Optional, Callable, Sequence
from dataclasses import dataclass, field

import chromadb
from chromadb.config import Settings

from core.logging_manager import get_logger

logger = get_logger("vector_store", "green")

VECTOR_DB_PATH = "data/memory/vector_db"

_STANDARD_META_KEYS = frozenset({
    "user_id", "memory_type", "importance", "timestamp", "access_count", "last_accessed"
})

def _extract_extra_metadata(meta: dict) -> dict:
    """Extract non-standard metadata keys for preservation in MemoryEntry.metadata."""
    return {k: v for k, v in meta.items() if k not in _STANDARD_META_KEYS}


@dataclass
class MemoryEntry:
    """一条长期记忆"""
    id: str
    user_id: str
    content: str
    memory_type: str  # "fact", "reflection", "summary"
    importance: int = 5  # 1-10
    timestamp: float = 0.0
    access_count: int = 0
    last_accessed: float = 0.0
    metadata: dict = field(default_factory=dict)


class VectorStore:
    """基于 ChromaDB 的向量存储"""

    def __init__(self, embedding_func: Optional[Callable[[list[str]], list[Sequence[float]]]] = None):
        os.makedirs(VECTOR_DB_PATH, exist_ok=True)

        if embedding_func is not None and inspect.iscoroutinefunction(embedding_func):
            raise TypeError(
                "embedding_func must be a synchronous callable, got async function. "
                "Wrap it with a sync adapter or pass the already-awaited embedding list instead."
            )
        self._embedding_func = embedding_func
        self._has_external_embeddings = False  # 是否存储过外部嵌入向量
        self._external_embeddings_lock = threading.Lock()

        self._client = chromadb.PersistentClient(
            path=VECTOR_DB_PATH,
            settings=Settings(anonymized_telemetry=False)
        )

        # 长期记忆集合
        self._collection = self._client.get_or_create_collection(
            name="long_term_memory",
            metadata={"hnsw:space": "cosine"}
        )

        # 通过集合元数据标志检测是否使用了外部嵌入
        col_meta = self._collection.metadata or {}
        if col_meta.get("external_embeddings"):
            self._has_external_embeddings = True
        elif self._collection.count() > 0:
            # 回退检测：获取一条现有记忆的嵌入维度
            try:
                sample = self._collection.get(limit=1, include=['embeddings'])
                if sample and sample.get("embeddings") and sample["embeddings"]:
                    emb = sample["embeddings"][0]
                    if emb and len(emb) > 0:
                        # ChromaDB 默认嵌入 (all-MiniLM-L6-v2) 是 384 维
                        if len(emb) != 384:
                            with self._external_embeddings_lock:
                                if not self._has_external_embeddings:
                                    self._has_external_embeddings = True
                                    self._persist_external_flag()
            except Exception as e:
                logger.debug(f"Could not detect embedding dimension: {e}")

        logger.info(f"VectorStore initialized (external_embeddings={self._has_external_embeddings})")

    @property
    def has_external_embeddings(self) -> bool:
        """Whether the collection uses external embeddings."""
        return self._has_external_embeddings

    def _persist_external_flag(self):
        """将外部嵌入标志持久化到 collection 元数据"""
        try:
            col_meta = dict(self._collection.metadata or {})
            col_meta.pop("hnsw:space", None)
            col_meta["external_embeddings"] = True
            self._collection.modify(metadata=col_meta)
        except Exception as e:
            logger.debug(f"Could not persist external_embeddings flag: {e}")

    def add_memory(self, entry: MemoryEntry, embedding: Optional[list[float]] = None):
        """添加一条记忆到向量库
        
        Args:
            embedding: 外部嵌入向量。传入 None 表示未提供，传入空列表视为无效。
        
        Raises:
            ValueError: 当外部嵌入模式已启用但未提供有效 embedding 时抛出。
        """
        metadata = {
            "user_id": entry.user_id,
            "memory_type": entry.memory_type,
            "importance": entry.importance,
            "timestamp": entry.timestamp or time.time(),
            "access_count": entry.access_count,
            "last_accessed": entry.last_accessed or time.time(),
        }
        metadata.update(entry.metadata)

        if embedding is not None:
            if not embedding:
                logger.error(f"Empty embedding provided for memory id={entry.id}, type={entry.memory_type}, len={len(entry.content)}")
                raise ValueError("Embedding must be a non-empty list of floats")
            # 有外部嵌入，使用 upsert 存储文档+向量
            with self._external_embeddings_lock:
                if not self._has_external_embeddings:
                    self._has_external_embeddings = True
                    self._persist_external_flag()
            self._collection.upsert(
                ids=[entry.id],
                documents=[entry.content],
                metadatas=[metadata],
                embeddings=[embedding],
            )
        elif self._embedding_func is not None:
            # 使用构造时注入的嵌入函数生成向量
            try:
                generated = self._embedding_func([entry.content])
                if inspect.isawaitable(generated):
                    raise TypeError(
                        "embedding_func returned a coroutine/awaitable. "
                        "Pass a synchronous callable or the already-awaited embedding list."
                    )
                if generated and generated[0] and len(generated[0]) > 0:
                    with self._external_embeddings_lock:
                        if not self._has_external_embeddings:
                            self._has_external_embeddings = True
                            self._persist_external_flag()
                    self._collection.upsert(
                        ids=[entry.id],
                        documents=[entry.content],
                        metadatas=[metadata],
                        embeddings=[generated[0]],
                    )
                else:
                    logger.warning(f"embedding_func returned empty result for id={entry.id}, type={entry.memory_type}, len={len(entry.content)}")
                    raise ValueError("embedding_func returned empty or invalid embedding")
            except ValueError:
                raise
            except Exception as e:
                logger.error(f"embedding_func failed: {e}")
                raise ValueError(f"Failed to generate embedding via embedding_func: {e}") from e
        elif self._has_external_embeddings:
            # 已启用外部嵌入但未提供，抛出异常而非静默丢失数据
            logger.error(f"External embeddings enabled but no embedding provided for id={entry.id}, type={entry.memory_type}, len={len(entry.content)}")
            raise ValueError(
                "Collection uses external embeddings but no embedding was provided. "
                "Provide an embedding or disable external embedding mode."
            )
        else:
            # 没有外部嵌入，使用 ChromaDB 默认嵌入函数
            self._collection.upsert(
                ids=[entry.id],
                documents=[entry.content],
                metadatas=[metadata],
            )

        logger.debug(f"Memory added: id={entry.id}, type={entry.memory_type}, len={len(entry.content)}")

    def search(self, query_text: Optional[str] = None, query_embedding: Optional[list[float]] = None,
               user_id: Optional[str] = None, memory_type: Optional[str] = None,
               k: int = 5, threshold: Optional[float] = None,
               update_access: bool = True) -> list[MemoryEntry]:
        """语义搜索记忆
        
        Args:
            update_access: 是否更新访问计数，内部去重搜索时应设为 False
        """
        # 如果集合使用了外部嵌入，拒绝 query_text 搜索（避免维度冲突）
        if query_text and not query_embedding and self._has_external_embeddings:
            logger.debug("Rejecting text search: collection uses external embeddings, use query_embedding instead")
            return []

        where_conditions = []
        if user_id:
            where_conditions.append({"user_id": user_id})
        if memory_type:
            where_conditions.append({"memory_type": memory_type})

        query_kwargs = {
            "n_results": k,
        }

        if query_embedding:
            query_kwargs["query_embeddings"] = [query_embedding]
        elif query_text:
            query_kwargs["query_texts"] = [query_text]
        else:
            return []

        # ChromaDB 多条件需要 $and
        if len(where_conditions) > 1:
            query_kwargs["where"] = {"$and": where_conditions}
        elif len(where_conditions) == 1:
            query_kwargs["where"] = where_conditions[0]

        try:
            results = self._collection.query(**query_kwargs)
        except Exception as e:
            logger.error(f"Vector search error: {e}")
            return []

        entries = []
        if results and results["ids"] and results["ids"][0]:
            ids = results["ids"][0]
            documents = results["documents"][0]
            metadatas = results["metadatas"][0]
            distances = results.get("distances", [[]])[0]

            for i, doc_id in enumerate(ids):
                # cosine distance, smaller = more similar
                if threshold is not None and distances and distances[i] > threshold:
                    continue

                meta = metadatas[i] if metadatas else {}
                entry = MemoryEntry(
                    id=doc_id,
                    user_id=meta.get("user_id", ""),
                    content=documents[i],
                    memory_type=meta.get("memory_type", "fact"),
                    importance=meta.get("importance", 5),
                    timestamp=meta.get("timestamp", 0),
                    access_count=meta.get("access_count", 0),
                    last_accessed=meta.get("last_accessed", 0),
                    metadata=_extract_extra_metadata(meta),
                )

                # 更新访问计数（内部去重搜索时不更新）
                if update_access:
                    now = time.time()
                    entry.access_count += 1
                    entry.last_accessed = now
                    self._collection.update(
                        ids=[doc_id],
                        metadatas=[{
                            **meta,
                            "access_count": entry.access_count,
                            "last_accessed": now
                        }]
                    )
                entries.append(entry)

        return entries

    def get_by_user(self, user_id: str, memory_type: Optional[str] = None,
                    limit: int = 100) -> list[MemoryEntry]:
        """获取某用户的所有记忆"""
        where_conditions = [{"user_id": user_id}]
        if memory_type:
            where_conditions.append({"memory_type": memory_type})

        if len(where_conditions) > 1:
            where_filter = {"$and": where_conditions}
        else:
            where_filter = where_conditions[0]

        try:
            results = self._collection.get(
                where=where_filter,
                limit=limit
            )
        except Exception as e:
            logger.error(f"Get by user error: {e}")
            return []

        entries = []
        if results and results["ids"]:
            for i, doc_id in enumerate(results["ids"]):
                meta = results["metadatas"][i] if results["metadatas"] else {}
                entries.append(MemoryEntry(
                    id=doc_id,
                    user_id=meta.get("user_id", ""),
                    content=results["documents"][i],
                    memory_type=meta.get("memory_type", "fact"),
                    importance=meta.get("importance", 5),
                    timestamp=meta.get("timestamp", 0),
                    access_count=meta.get("access_count", 0),
                    last_accessed=meta.get("last_accessed", 0),
                    metadata=_extract_extra_metadata(meta),
                ))
        return entries

    def update_memory(self, memory_id: str, content: Optional[str] = None,
                      importance: Optional[int] = None, metadata: Optional[dict] = None,
                      embedding: Optional[list[float]] = None):
        """更新一条记忆
        
        Args:
            embedding: 当 content 更新时应同时提供新的 embedding，
                       避免 ChromaDB 使用默认嵌入函数导致维度不匹配
        """
        try:
            if embedding is not None and len(embedding) == 0:
                logger.error(f"Empty embedding provided for update memory_id={memory_id}")
                return False

            existing = self._collection.get(ids=[memory_id])
            if not existing or not existing["ids"]:
                return False

            old_meta = existing["metadatas"][0] if existing["metadatas"] else {}

            new_meta = dict(old_meta)
            if importance is not None:
                new_meta["importance"] = importance
            if metadata:
                new_meta.update(metadata)

            update_kwargs = {
                "ids": [memory_id],
                "metadatas": [new_meta],
            }
            if content is not None:
                update_kwargs["documents"] = [content]
                if embedding and len(embedding) > 0:
                    update_kwargs["embeddings"] = [embedding]
                    with self._external_embeddings_lock:
                        if not self._has_external_embeddings:
                            self._has_external_embeddings = True
                            self._persist_external_flag()
                elif self._embedding_func is not None:
                    # 使用构造时注入的嵌入函数生成向量
                    try:
                        generated = self._embedding_func([content])
                        if inspect.isawaitable(generated):
                            raise TypeError(
                                "embedding_func returned a coroutine/awaitable. "
                                "Pass a synchronous callable or the already-awaited embedding list."
                            )
                        if generated and generated[0] and len(generated[0]) > 0:
                            update_kwargs["embeddings"] = [generated[0]]
                            with self._external_embeddings_lock:
                                if not self._has_external_embeddings:
                                    self._has_external_embeddings = True
                                    self._persist_external_flag()
                        else:
                            logger.warning(
                                f"update_memory: embedding_func returned empty result for {memory_id}, "
                                f"skipping update"
                            )
                            return False
                    except Exception as e:
                        logger.warning(
                            f"update_memory: embedding_func failed for {memory_id}: {e}, "
                            f"skipping update"
                        )
                        return False
                elif self._has_external_embeddings:
                    logger.warning(
                        f"update_memory: content changed but no valid embedding provided in external-embedding mode "
                        f"(embedding={'empty list' if embedding is not None else 'None'}), "
                        f"skipping update for {memory_id}"
                    )
                    return False

            self._collection.update(**update_kwargs)
            return True
        except Exception as e:
            logger.error(f"Update memory error: {e}")
            return False

    def get_memory_by_id(self, memory_id: str) -> Optional[MemoryEntry]:
        """按 ID 精确查找一条记忆"""
        try:
            results = self._collection.get(ids=[memory_id])
            if results and results["ids"]:
                meta = results["metadatas"][0] if results["metadatas"] else {}
                return MemoryEntry(
                    id=results["ids"][0],
                    user_id=meta.get("user_id", ""),
                    content=results["documents"][0],
                    memory_type=meta.get("memory_type", "fact"),
                    importance=meta.get("importance", 5),
                    timestamp=meta.get("timestamp", 0),
                    access_count=meta.get("access_count", 0),
                    last_accessed=meta.get("last_accessed", 0),
                    metadata=_extract_extra_metadata(meta),
                )
        except Exception as e:
            logger.debug(f"get_memory_by_id({memory_id}) failed: {e}")
        return None

    def delete_memory(self, memory_id: str) -> bool:
        """删除一条记忆"""
        try:
            self._collection.delete(ids=[memory_id])
            return True
        except Exception as e:
            logger.error(f"Delete memory error: {e}")
            return False

    def get_all_memories(self, limit: int = 1000, offset: int = 0) -> list[MemoryEntry]:
        """获取所有记忆（用于遗忘机制扫描）

        注意：默认 limit=1000，当记忆量超过此值时只返回部分结果。
        如需获取全部记忆，请传入更大的 limit 值或使用分页查询。

        Args:
            limit: 每页返回的最大条目数
            offset: 跳过前 offset 条结果（用于分页）
        """
        try:
            results = self._collection.get(limit=limit, offset=offset)
        except Exception as e:
            logger.error(f"Get all memories error: {e}")
            return []

        entries = []
        if results and results["ids"]:
            for i, doc_id in enumerate(results["ids"]):
                meta = results["metadatas"][i] if results["metadatas"] else {}
                entries.append(MemoryEntry(
                    id=doc_id,
                    user_id=meta.get("user_id", ""),
                    content=results["documents"][i],
                    memory_type=meta.get("memory_type", "fact"),
                    importance=meta.get("importance", 5),
                    timestamp=meta.get("timestamp", 0),
                    access_count=meta.get("access_count", 0),
                    last_accessed=meta.get("last_accessed", 0),
                    metadata=_extract_extra_metadata(meta),
                ))
        return entries

    def count(self) -> int:
        """返回记忆总数"""
        return self._collection.count()

    @staticmethod
    def generate_id() -> str:
        return uuid.uuid4().hex[:12]
