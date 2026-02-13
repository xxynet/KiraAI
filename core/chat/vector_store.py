"""
向量数据库存储层，使用 ChromaDB 实现长期记忆的向量检索
"""
import os
import time
import uuid
from typing import Optional
from dataclasses import dataclass, field

import chromadb
from chromadb.config import Settings

from core.logging_manager import get_logger

logger = get_logger("vector_store", "green")

VECTOR_DB_PATH = "data/memory/vector_db"


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

    def __init__(self, embedding_func=None):
        os.makedirs(VECTOR_DB_PATH, exist_ok=True)

        self._embedding_func = embedding_func

        self._client = chromadb.PersistentClient(
            path=VECTOR_DB_PATH,
            settings=Settings(anonymized_telemetry=False)
        )

        # 长期记忆集合
        self._collection = self._client.get_or_create_collection(
            name="long_term_memory",
            metadata={"hnsw:space": "cosine"}
        )

        logger.info("VectorStore initialized")

    def add_memory(self, entry: MemoryEntry, embedding: list[float] = None):
        """添加一条记忆到向量库"""
        metadata = {
            "user_id": entry.user_id,
            "memory_type": entry.memory_type,
            "importance": entry.importance,
            "timestamp": entry.timestamp or time.time(),
            "access_count": entry.access_count,
            "last_accessed": entry.last_accessed or time.time(),
        }
        metadata.update(entry.metadata)

        kwargs = {
            "ids": [entry.id],
            "documents": [entry.content],
            "metadatas": [metadata],
        }

        if embedding:
            kwargs["embeddings"] = [embedding]

        self._collection.upsert(**kwargs)
        logger.debug(f"Memory added: [{entry.memory_type}] {entry.content[:50]}...")

    def search(self, query_text: str = None, query_embedding: list[float] = None,
               user_id: str = None, memory_type: str = None,
               k: int = 5, threshold: float = None,
               update_access: bool = True) -> list[MemoryEntry]:
        """语义搜索记忆
        
        Args:
            update_access: 是否更新访问计数，内部去重搜索时应设为 False
        """
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
                )

                # 更新访问计数（内部去重搜索时不更新）
                if update_access:
                    self._collection.update(
                        ids=[doc_id],
                        metadatas=[{
                            **meta,
                            "access_count": entry.access_count + 1,
                            "last_accessed": time.time()
                        }]
                    )
                entries.append(entry)

        return entries

    def get_by_user(self, user_id: str, memory_type: str = None,
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
                ))
        return entries

    def update_memory(self, memory_id: str, content: str = None,
                      importance: int = None, metadata: dict = None):
        """更新一条记忆"""
        try:
            existing = self._collection.get(ids=[memory_id])
            if not existing or not existing["ids"]:
                return False

            old_meta = existing["metadatas"][0] if existing["metadatas"] else {}
            old_doc = existing["documents"][0] if existing["documents"] else ""

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

            self._collection.update(**update_kwargs)
            return True
        except Exception as e:
            logger.error(f"Update memory error: {e}")
            return False

    def delete_memory(self, memory_id: str) -> bool:
        """删除一条记忆"""
        try:
            self._collection.delete(ids=[memory_id])
            return True
        except Exception as e:
            logger.error(f"Delete memory error: {e}")
            return False

    def get_all_memories(self, limit: int = 1000) -> list[MemoryEntry]:
        """获取所有记忆（用于遗忘机制扫描）"""
        try:
            results = self._collection.get(limit=limit)
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
                ))
        return entries

    def count(self) -> int:
        """返回记忆总数"""
        return self._collection.count()

    @staticmethod
    def generate_id() -> str:
        return uuid.uuid4().hex[:12]
