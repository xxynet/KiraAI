"""
新版记忆系统 - 双脑架构
- 短期记忆：滑动窗口对话历史（保持原有功能）
- 长期记忆：ChromaDB 向量检索（事实、反思、摘要）
- 用户画像：结构化 JSON 存储
- 海马体：后台事实提取 + 反思生成
- 遗忘机制：基于重要性和访问频率的记忆衰减
"""
import asyncio
import ast
import json
import os
import re
import time
import uuid
from typing import Dict, List, Optional
from threading import Lock

from core.logging_manager import get_logger
from core.config import KiraConfig

from .session import Session
from .vector_store import VectorStore, MemoryEntry
from .user_profile import UserProfileStore, UserProfile

logger = get_logger("memory_manager", "green")

CHAT_MEMORY_PATH: str = "data/memory/chat_memory.json"
CORE_MEMORY_PATH: str = "data/memory/core.txt"


class MemoryManager:
    """双脑架构记忆管理器
    
    快系统（Fast Loop）：对话时检索记忆、维护短期对话历史
    慢系统（Slow Loop）：后台提取事实、生成反思、更新画像、遗忘清理
    """

    def __init__(self, kira_config: KiraConfig, llm_client=None):
        self.kira_config = kira_config
        self.max_memory_length = int(kira_config["bot_config"].get("bot").get("max_memory_length"))
        self.chat_memory_path = CHAT_MEMORY_PATH
        self.core_memory_path = CORE_MEMORY_PATH

        self.memory_lock = Lock()

        # === 短期记忆（原有） ===
        self.chat_memory = self._load_memory(self.chat_memory_path)
        self._ensure_memory_format()

        # === 长期记忆（向量库） ===
        self.vector_store = VectorStore()

        # === 用户画像 ===
        self.user_profile_store = UserProfileStore()

        # === LLM 客户端（用于海马体后台处理） ===
        self._llm_client = llm_client

        # === 后台处理缓冲区 ===
        self._pending_conversations: Dict[str, list] = {}
        self._hippocampus_threshold = 3  # 每 N 轮触发一次海马体处理
        self._hippocampus_lock = Lock()
        self._background_tasks: set = set()  # 持久化后台任务引用
        self._background_tasks_lock = Lock()  # 保护 _background_tasks 集合

        logger.info("MemoryManager initialized (dual-brain architecture)")

    def set_llm_client(self, llm_client):
        """延迟设置 LLM 客户端"""
        self._llm_client = llm_client

    # ==========================================
    # 短期记忆（原有功能完整保留）
    # ==========================================

    @staticmethod
    def _load_memory(path: str) -> Dict[str, dict]:
        """加载记忆文件"""
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    memory_content = f.read()
                    if memory_content.strip():
                        return json.loads(memory_content)
                    else:
                        return {}
            except Exception as e:
                import traceback
                err = traceback.format_exc()
                logger.error(f"Error loading memory from {path}: {e}")
                logger.error(err)
                return {}
        else:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            return {}

    def _ensure_memory_format(self):
        for session in self.chat_memory:
            session_content = self.chat_memory[session]
            if isinstance(session_content, dict):
                continue

            if isinstance(session_content, list):
                self.chat_memory[session] = {
                    "title": "",
                    "description": "",
                    "memory": session_content
                }
        self._save_memory(self.chat_memory, self.chat_memory_path)

    def _save_memory(self, memory: Dict[str, dict] = None, path: str = None):
        """保存记忆到文件"""
        if not memory:
            memory = self.chat_memory
        if not path:
            path = self.chat_memory_path
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(json.dumps(memory, indent=4, ensure_ascii=False))
        except Exception as e:
            logger.error(f"Error saving memory to {path}: {e}")

    def get_session_info(self, session: str):
        parts = session.split(":", maxsplit=2)
        if len(parts) != 3:
            raise ValueError("Invalid session ID")
        if session not in self.chat_memory:
            self.chat_memory[session] = {
                "title": "",
                "description": "",
                "memory": []
            }
        return Session(
            adapter_name=parts[0],
            session_type=parts[1],
            session_id=parts[2],
            session_title=self.chat_memory[session]["title"],
            session_description=self.chat_memory[session]["description"]
        )

    def update_session_info(self, session: str, title: str = None, description: str = None):
        with self.memory_lock:
            if session not in self.chat_memory:
                self.chat_memory[session] = {
                    "title": "",
                    "description": "",
                    "memory": []
                }
            if title:
                self.chat_memory[session]["title"] = title
            if description:
                self.chat_memory[session]["description"] = description
            self._save_memory()

    def get_memory_count(self, session: str) -> int:
        if session not in self.chat_memory:
            return 0
        return len(self.chat_memory[session].get("memory", []))

    def fetch_memory(self, session: str):
        if session not in self.chat_memory:
            self.chat_memory[session] = {
                "title": "",
                "description": "",
                "memory": []
            }
            return []
        else:
            mem_list = self.chat_memory[session].get("memory", [])
            messages = []
            for chunk in mem_list:
                for message in chunk:
                    messages.append(message)
            return messages

    def read_memory(self, session: str):
        if session not in self.chat_memory:
            self.chat_memory[session] = {
                "title": "",
                "description": "",
                "memory": []
            }
            return []
        else:
            return self.chat_memory[session].get("memory", [])

    def write_memory(self, session: str, memory: list[list[dict]]):
        with self.memory_lock:
            self.chat_memory[session]["memory"] = memory
            self._save_memory(self.chat_memory, self.chat_memory_path)
        logger.info(f"Memory written for {session}")

    def update_memory(self, session: str, new_chunk):
        with self.memory_lock:
            self.chat_memory[session]["memory"].append(new_chunk)
            if len(self.chat_memory[session]["memory"]) > self.max_memory_length:
                self.chat_memory[session]["memory"] = self.chat_memory[session]["memory"][1:]
            self._save_memory(self.chat_memory, self.chat_memory_path)
        logger.info(f"Memory updated for {session}")

        # 将对话加入待处理缓冲区，异步触发海马体
        self._buffer_for_hippocampus(session, new_chunk)

    def delete_session(self, session: str):
        with self.memory_lock:
            self.chat_memory.pop(session)
            self._save_memory(self.chat_memory, self.chat_memory_path)
        logger.info(f"Memory deleted for {session}")

    def get_core_memory(self):
        os.makedirs(os.path.dirname(self.core_memory_path), exist_ok=True)
        if not os.path.exists(self.core_memory_path):
            with open(self.core_memory_path, "w", encoding="utf-8") as f:
                f.write("")
            return ""
        with open(self.core_memory_path, "r", encoding='utf-8') as mem:
            lines = mem.readlines()
        memory_str = ""
        for i, line in enumerate(lines):
            memory_str += f"[{i}] {line}"
        return memory_str

    # ==========================================
    # 长期记忆（向量检索）
    # ==========================================

    async def recall(self, query: str, user_id: Optional[str] = None, k: int = 5) -> list[MemoryEntry]:
        """检索与查询相关的长期记忆（快系统 - 对话前调用）
        
        Args:
            query: 当前用户输入
            user_id: 可选的用户ID过滤
            k: 返回最相关的 k 条记忆（最小为 1）
        """
        try:
            k = int(k)
        except (TypeError, ValueError):
            k = 5
        k = max(1, k)
        try:
            # 使用外部 embedding 模型生成向量进行搜索
            # 不回退到 ChromaDB 默认文本搜索，避免嵌入维度不匹配
            if self._llm_client:
                try:
                    embeddings = await self._llm_client.embed([query])
                    if embeddings and embeddings[0]:
                        return await asyncio.to_thread(
                            self.vector_store.search,
                            query_embedding=embeddings[0],
                            user_id=user_id,
                            k=k
                        )
                except Exception as e:
                    logger.warning(f"Embedding search failed: {e}")

            # 无外部 embedding 模型时，尝试使用 ChromaDB 内置文本搜索
            if not self.vector_store.has_external_embeddings:
                try:
                    return await asyncio.to_thread(
                        self.vector_store.search,
                        query_text=query,
                        user_id=user_id,
                        k=k
                    )
                except Exception as e:
                    logger.error(f"Text-based recall fallback failed: {e}")
            else:
                logger.debug("No embedding model available and collection uses external embeddings, skipping recall")
            return []
        except Exception as e:
            logger.error(f"Recall error: {e}")
            return []

    def format_recalled_memories(self, memories: list[MemoryEntry]) -> str:
        """将检索到的记忆格式化为 prompt 文本"""
        if not memories:
            return "暂无相关长期记忆"
        parts = []
        for mem in memories:
            type_label = {"fact": "事实", "reflection": "洞察", "summary": "摘要"}.get(mem.memory_type, mem.memory_type)
            parts.append(f"[{type_label}] {mem.content}")
        return "\n".join(parts)

    # ==========================================
    # 用户画像
    # ==========================================

    def get_user_profile(self, user_id: str) -> UserProfile:
        """获取用户画像"""
        return self.user_profile_store.get_profile(user_id)

    def get_user_profile_prompt(self, user_id: str) -> str:
        """获取用户画像的 prompt 文本"""
        return self.user_profile_store.get_profile_prompt(user_id)

    async def update_user_interaction(self, user_id: str, platform: str = "", nickname: str = ""):
        """更新用户交互信息"""
        updates = {}
        if platform:
            updates["platform"] = platform
        if nickname:
            updates["nickname"] = nickname
        await asyncio.to_thread(self.user_profile_store.increment_and_update_profile, user_id, **updates)

    # ==========================================
    # 海马体（慢系统 - 后台处理）
    # ==========================================

    def _buffer_for_hippocampus(self, session: str, new_chunk):
        """将新对话缓冲到待处理队列"""
        chunks_to_process = None
        with self._hippocampus_lock:
            if session not in self._pending_conversations:
                self._pending_conversations[session] = []
            self._pending_conversations[session].append(new_chunk)

            # 当累积到阈值时，原子地取出并清空
            if len(self._pending_conversations[session]) >= self._hippocampus_threshold:
                chunks_to_process = self._pending_conversations[session][:]
                self._pending_conversations[session] = []

        if chunks_to_process is not None:
            try:
                loop = asyncio.get_running_loop()
                task = loop.create_task(
                    self._hippocampus_process(session, chunks_to_process)
                )
                with self._background_tasks_lock:
                    self._background_tasks.add(task)
                task.add_done_callback(self._on_background_task_done)
            except RuntimeError:
                # 没有运行中的事件循环，恢复已取出的数据块
                with self._hippocampus_lock:
                    if session in self._pending_conversations:
                        self._pending_conversations[session] = chunks_to_process + self._pending_conversations[session]
                    else:
                        self._pending_conversations[session] = chunks_to_process
                logger.debug("No running event loop, skipping hippocampus processing")

    def _on_background_task_done(self, task: asyncio.Task):
        """后台任务完成回调：清理引用并记录异常"""
        with self._background_tasks_lock:
            self._background_tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error("Background hippocampus task failed", exc_info=(type(exc), exc, exc.__traceback__))

    async def _hippocampus_process(self, session: str, chunks: list):
        """海马体后台处理：提取事实 → 去重更新 → 生成反思 → 更新画像"""
        if not self._llm_client:
            logger.debug("LLM client not set, skipping hippocampus processing")
            return

        try:
            # 1. 提取事实
            conversation_text = self._chunks_to_text(chunks)
            facts = await self._extract_facts(conversation_text)

            if not facts:
                return

            # 2. 去重与写入向量库
            user_id = self._extract_user_id_from_session(session)
            for fact in facts:
                await self._deduplicate_and_store(fact, user_id)

            # 3. 生成反思（如果积累了足够的事实）
            user_memories = await asyncio.to_thread(
                self.vector_store.get_by_user,
                user_id,
                "fact",
                10,
            )
            if len(user_memories) >= 5:
                await self._generate_reflection(user_id, user_memories)

            # 4. 更新用户画像
            await self._update_profile_from_facts(user_id, facts)

            logger.info(f"Hippocampus processing completed for session {session}")
        except Exception as e:
            logger.error(f"Hippocampus processing error: {e}")

    async def _extract_facts(self, conversation_text: str) -> list[dict]:
        """从对话中提取事实"""
        prompt = f"""分析以下对话片段，提取关于用户的关键事实。忽略寒暄和无意义内容。

对话:
{conversation_text}

请以 JSON 数组格式输出，每条事实包含：
- "subject": 主语（"user" 或具体人名）
- "content": 事实描述
- "importance": 重要性评分(1-10)

只输出 JSON 数组，不要有其他内容。如果没有值得记录的事实，输出空数组 []。"""

        try:
            resp = await self._llm_client.chat([{"role": "user", "content": prompt}])
            if resp and resp.text_response:
                text = resp.text_response.strip()
                # 尝试提取 JSON
                if text.startswith("```"):
                    text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                # 提取第一个 JSON 数组片段
                start = text.find("[")
                end = text.rfind("]")
                if start != -1 and end != -1 and end > start:
                    text = text[start:end + 1]
                # 尝试解析 JSON
                try:
                    facts = json.loads(text)
                except json.JSONDecodeError:
                    # 移除尾随逗号后重试
                    text = re.sub(r',\s*([}\]])', r'\1', text)
                    try:
                        facts = json.loads(text)
                    except json.JSONDecodeError:
                        # 最后回退到 ast.literal_eval
                        try:
                            obj = ast.literal_eval(text)
                            facts = json.loads(json.dumps(obj))
                        except (ValueError, SyntaxError):
                            facts = None
                if isinstance(facts, list):
                    cleaned = []
                    for f in facts:
                        if not isinstance(f, dict) or "content" not in f:
                            continue
                        # Normalize importance to int
                        raw_imp = f.get("importance")
                        if raw_imp is None or raw_imp == "":
                            f["importance"] = 5
                        else:
                            try:
                                f["importance"] = int(float(raw_imp))
                            except (ValueError, TypeError):
                                f["importance"] = 5
                        cleaned.append(f)
                    return cleaned
        except Exception as e:
            logger.error(f"Fact extraction error: {e}")
        return []

    async def _deduplicate_and_store(self, fact: dict, user_id: str):
        """去重并存储事实到向量库"""
        content = fact.get("content", "")
        importance = fact.get("importance", 5)

        if not content:
            return

        # 搜索已有类似记忆（带距离阈值，避免无关记忆触发 LLM 检查）
        # 只使用外部 embedding 模型搜索，不回退到 ChromaDB 默认文本搜索（避免维度冲突）
        existing = []
        initial_embedding = None
        if self._llm_client:
            try:
                embeddings = await self._llm_client.embed([content])
                if embeddings and embeddings[0]:
                    initial_embedding = embeddings[0]
                    existing = await asyncio.to_thread(
                        self.vector_store.search,
                        query_embedding=initial_embedding,
                        user_id=user_id,
                        memory_type="fact",
                        k=3,
                        threshold=0.5,
                        update_access=False
                    )
            except Exception as e:
                logger.debug(f"Embedding search for dedup failed, skipping dedup: {e}")

        # 检查是否有高度相似的记忆（需要 LLM 判断）
        if existing:
            most_similar = existing[0]
            # 让 LLM 判断是冲突、补充还是全新
            decision = await self._check_conflict(content, most_similar.content)

            if decision == "duplicate":
                # 重复的，跳过
                logger.debug(f"Duplicate memory skipped (len={len(content)})")
                return
            elif decision == "update":
                # 冲突/更新，合并
                merged = await self._merge_facts(most_similar.content, content)
                # 为合并后的内容生成新的 embedding，避免维度不匹配
                merged_embedding = None
                if self._llm_client:
                    try:
                        embs = await self._llm_client.embed([merged])
                        if embs and embs[0]:
                            merged_embedding = embs[0]
                    except Exception:
                        logger.debug("Failed to generate embedding for merged content")
                updated = await asyncio.to_thread(
                    self.vector_store.update_memory,
                    most_similar.id,
                    content=merged,
                    importance=max(importance, most_similar.importance),
                    embedding=merged_embedding
                )
                if updated:
                    logger.info(
                        f"Memory updated (merged): id={most_similar.id}, "
                        f"type={most_similar.memory_type}, len={len(merged)}, "
                        f"embedding={'present' if merged_embedding else 'None'}"
                    )
                else:
                    logger.warning(
                        f"update_memory failed for {most_similar.id} "
                        f"(embedding={'present' if merged_embedding else 'None'})"
                    )
                return

        # 全新事实，添加
        entry = MemoryEntry(
            id=VectorStore.generate_id(),
            user_id=user_id,
            content=content,
            memory_type="fact",
            importance=importance,
            timestamp=time.time(),
        )

        # 尝试用 embedding 存储
        embedding = initial_embedding
        if embedding is None and self._llm_client:
            try:
                embeddings = await self._llm_client.embed([content])
                if embeddings and embeddings[0]:
                    embedding = embeddings[0]
            except Exception:
                logger.debug("Failed to generate embedding for new memory")

        try:
            await asyncio.to_thread(self.vector_store.add_memory, entry, embedding=embedding)
            logger.info(f"New memory stored: type={entry.memory_type}, id={entry.id}, len={len(content)}, embedding={'present' if embedding else 'None'}")
        except ValueError as e:
            logger.warning(f"Could not store memory (no embedding available): {e}")

    async def _check_conflict(self, new_content: str, existing_content: str) -> str:
        """用 LLM 判断新旧记忆的关系: duplicate / update / new"""
        prompt = f"""比较以下两条信息，判断它们的关系：

已有信息: {existing_content}
新信息: {new_content}

只输出以下三个选项之一：
- "duplicate"：新信息与已有信息基本相同，无需记录
- "update"：新信息是对已有信息的更新或补充，需要合并
- "new"：新信息与已有信息无关，是全新信息

只输出选项文本，不要有其他内容。"""

        try:
            resp = await self._llm_client.chat([{"role": "user", "content": prompt}])
            if resp and resp.text_response:
                result = resp.text_response.strip().strip('"').lower()
                if result in ("duplicate", "update", "new"):
                    return result
        except Exception as e:
            logger.error(f"Conflict check error: {e}")
        return "new"

    async def _merge_facts(self, existing: str, new: str) -> str:
        """合并两条事实"""
        prompt = f"""将以下两条信息合并为一条，保留所有有用信息：

已有信息: {existing}
新信息: {new}

直接输出合并后的结果，不要有其他内容。"""

        try:
            resp = await self._llm_client.chat([{"role": "user", "content": prompt}])
            if resp and resp.text_response:
                return resp.text_response.strip()
        except Exception as e:
            logger.error(f"Merge facts error: {e}")
        return f"{existing}；{new}"

    async def _generate_reflection(self, user_id: str, recent_facts: list[MemoryEntry]):
        """从累积的事实中生成反思/洞察"""
        facts_text = "\n".join(f"{i + 1}. {f.content}" for i, f in enumerate(recent_facts))

        prompt = f"""基于以下关于用户的事实，你能推断出什么更高层面的洞察？

事实:
{facts_text}

请输出 1-3 条简洁的洞察，每条一行，不需要编号。只输出洞察内容，不要有其他内容。"""

        try:
            resp = await self._llm_client.chat([{"role": "user", "content": prompt}])
            if resp and resp.text_response:
                insights = [line.strip() for line in resp.text_response.strip().split("\n") if line.strip()]
                for insight in insights:
                    # 生成 embedding（只调用一次，同时用于去重检查和存储）
                    embedding = None
                    if self._llm_client:
                        try:
                            embs = await self._llm_client.embed([insight])
                            if embs and embs[0]:
                                embedding = embs[0]
                        except Exception:
                            logger.debug("Failed to generate embedding for reflection")

                    # 检查是否已有高度相似的反思（距离阈值 0.3）
                    existing = []
                    if embedding:
                        existing = await asyncio.to_thread(
                            self.vector_store.search,
                            query_embedding=embedding,
                            user_id=user_id,
                            memory_type="reflection",
                            k=1,
                            threshold=0.3,
                            update_access=False,
                        )
                    if existing:
                        logger.debug(f"Similar reflection already exists, skipped (len={len(insight)})")
                        continue

                    entry = MemoryEntry(
                        id=VectorStore.generate_id(),
                        user_id=user_id,
                        content=insight,
                        memory_type="reflection",
                        importance=7,
                        timestamp=time.time(),
                    )

                    try:
                        await asyncio.to_thread(self.vector_store.add_memory, entry, embedding=embedding)
                        logger.info(f"Reflection stored: id={entry.id}, len={len(insight)}, embedding={'present' if embedding else 'None'}")
                    except Exception as e:
                        logger.error(f"Failed to store reflection (id={entry.id}, len={len(insight)}, embedding={'present' if embedding else 'None'}): {e}")
                        continue
        except Exception as e:
            logger.error(f"Reflection generation error: {e}")

    async def _update_profile_from_facts(self, user_id: str, facts: list[dict]):
        """从提取的事实更新用户画像"""
        for fact in facts:
            content = fact.get("content", "")
            importance = fact.get("importance", 5)
            if importance >= 7:
                await asyncio.to_thread(self.user_profile_store.add_fact, user_id, content)

    # ==========================================
    # 遗忘机制
    # ==========================================

    async def run_forgetting_cycle(self):
        """执行遗忘周期：清理低价值记忆（分页遍历全部记忆）"""
        now = time.time()
        removed_count = 0
        removed_ids: set = set()
        all_memories: list[MemoryEntry] = []

        # 分页获取全部记忆
        page_size = 1000
        offset = 0
        while True:
            page = await asyncio.to_thread(self.vector_store.get_all_memories, limit=page_size, offset=offset)
            if not page:
                break
            all_memories.extend(page)
            if len(page) < page_size:
                break
            offset += page_size

        for mem in all_memories:
            score = self._calculate_retention_score(mem, now)

            if score < 0.2:
                # 太低价值，直接删除
                if await asyncio.to_thread(self.vector_store.delete_memory, mem.id):
                    removed_count += 1
                    removed_ids.add(mem.id)
                else:
                    logger.warning(f"Failed to delete memory {mem.id} during forgetting cycle")
            elif score < 0.4 and mem.memory_type == "fact":
                # 低价值事实，标记降级
                if not await asyncio.to_thread(
                    self.vector_store.update_memory,
                    mem.id,
                    importance=max(1, mem.importance - 1)
                ):
                    logger.warning(f"Failed to downgrade memory {mem.id} during forgetting cycle")

        if removed_count > 0:
            logger.info(f"Forgetting cycle: removed {removed_count} memories")

        # 尝试摘要化：复用已获取的记忆列表（排除已删除的）
        surviving_memories = [m for m in all_memories if m.id not in removed_ids]
        await self._summarize_old_memories(surviving_memories)

    @staticmethod
    def _calculate_retention_score(mem: MemoryEntry, now: float) -> float:
        """计算记忆保留分数
        
        综合考虑：重要性、时间衰减、访问频率
        分数范围 0.0 ~ 1.0
        """
        # 时间衰减（天数）
        days_since_creation = (now - mem.timestamp) / 86400 if mem.timestamp else 30
        days_since_access = (now - mem.last_accessed) / 86400 if mem.last_accessed else 30

        # 重要性权重 (0.0 ~ 1.0)
        importance_score = mem.importance / 10.0

        # 时间衰减因子（基于最后访问，半衰期 30 天）
        access_decay = 0.5 ** (days_since_access / 30.0)

        # 创建时间衰减因子（半衰期 90 天，较慢的自然遗忘）
        creation_decay = 0.5 ** (days_since_creation / 90.0)

        # 访问频率加成
        access_bonus = min(mem.access_count * 0.05, 0.3)

        # 反思类型有更高保留权重
        type_bonus = 0.2 if mem.memory_type == "reflection" else 0.0

        score = (importance_score * 0.35) + (access_decay * 0.25) + (creation_decay * 0.1) + access_bonus + type_bonus
        return min(score, 1.0)

    async def _summarize_old_memories(self, all_memories: Optional[list[MemoryEntry]] = None):
        """将同一用户的老旧事实合并为摘要"""
        if not self._llm_client:
            return

        if all_memories is None:
            all_memories = []
            page_size = 1000
            offset = 0
            while True:
                page = await asyncio.to_thread(self.vector_store.get_all_memories, limit=page_size, offset=offset)
                if not page:
                    break
                all_memories.extend(page)
                if len(page) < page_size:
                    break
                offset += page_size
        now = time.time()

        # 按用户分组
        user_old_facts: Dict[str, list[MemoryEntry]] = {}
        for mem in all_memories:
            if mem.memory_type != "fact":
                continue
            days_old = (now - mem.timestamp) / 86400 if mem.timestamp else 0
            if days_old > 30:  # 超过 30 天的事实
                if mem.user_id not in user_old_facts:
                    user_old_facts[mem.user_id] = []
                user_old_facts[mem.user_id].append(mem)

        for user_id, old_facts in user_old_facts.items():
            if len(old_facts) < 5:
                continue

            # 合并为摘要
            facts_text = "\n".join(f"- {f.content}" for f in old_facts)
            prompt = f"""将以下关于用户的多条事实合并为 1-2 条简洁的摘要：

{facts_text}

直接输出摘要，每条一行，不要有其他内容。"""

            try:
                resp = await self._llm_client.chat([{"role": "user", "content": prompt}])
                if resp and resp.text_response:
                    summaries = [line.strip() for line in resp.text_response.strip().split("\n") if line.strip()]
                    summaries_added = 0
                    for summary in summaries:
                        entry = MemoryEntry(
                            id=VectorStore.generate_id(),
                            user_id=user_id,
                            content=summary,
                            memory_type="summary",
                            importance=6,
                            timestamp=time.time(),
                        )
                        # 为摘要生成 embedding，避免 VectorStore 跳过无嵌入的记忆
                        summary_embedding = None
                        if self._llm_client:
                            try:
                                embs = await self._llm_client.embed([summary])
                                if embs and embs[0]:
                                    summary_embedding = embs[0]
                            except Exception:
                                logger.debug("Failed to generate embedding for summary")
                        try:
                            await asyncio.to_thread(self.vector_store.add_memory, entry, embedding=summary_embedding)
                            summaries_added += 1
                        except Exception as e:
                            logger.error(f"Failed to store summary (id={entry.id}): {e}")

                    # 仅在至少一条摘要成功写入后才删除旧事实
                    if summaries_added > 0:
                        deleted_count = 0
                        failed_ids = []
                        for old_fact in old_facts:
                            if await asyncio.to_thread(self.vector_store.delete_memory, old_fact.id):
                                deleted_count += 1
                            else:
                                failed_ids.append(old_fact.id)
                        if failed_ids:
                            logger.warning(f"Failed to delete {len(failed_ids)} old facts during summarization for user {user_id}: {failed_ids}")
                        logger.info(f"Summarized {len(old_facts)} old facts into {summaries_added} summaries for user {user_id} (deleted {deleted_count}/{len(old_facts)})")
                    else:
                        logger.warning(f"No summaries stored successfully, keeping {len(old_facts)} old facts for user {user_id}")
            except Exception as e:
                logger.error(f"Summarization error: {e}")

    # ==========================================
    # 工具方法
    # ==========================================

    @staticmethod
    def _chunks_to_text(chunks: list) -> str:
        """将对话 chunks 转为纯文本"""
        lines = []
        for chunk in chunks:
            for msg in chunk:
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                if role == "user":
                    lines.append(f"User: {content}")
                elif role == "assistant":
                    lines.append(f"Bot: {content}")
        return "\n".join(lines)

    @staticmethod
    def _extract_user_id_from_session(session: str) -> str:
        """从 session ID 提取会话标识
        
        session 格式: adapter:type:id
        - 私聊: adapter:pm:user_id → adapter:user_id
        - 群聊: adapter:gm:group_id → adapter:group:group_id
        群聊用 'group:' 前缀区分，避免与个人 user_id 冲突
        """
        parts = session.split(":", maxsplit=2)
        if len(parts) != 3:
            raise ValueError("Invalid session ID")
        session_type = parts[1]
        session_id = parts[2]
        if session_type == "gm":
            return f"{parts[0]}:group:{session_id}"
        return f"{parts[0]}:{session_id}"
