"""
用户画像存储层，使用 JSON 文件持久化用户结构化信息
"""
import copy
import json
import os
import tempfile
import time
from threading import Lock
from typing import Optional
from dataclasses import dataclass, field, fields, asdict

from core.logging_manager import get_logger

logger = get_logger("user_profile", "green")

USER_PROFILE_PATH = "data/memory/user_profiles.json"


@dataclass
class UserProfile:
    """用户画像"""
    user_id: str
    platform: str = ""
    name: str = ""
    nickname: str = ""
    traits: list[str] = field(default_factory=list)
    preferences: dict = field(default_factory=dict)
    relationships: dict = field(default_factory=dict)
    facts: list[str] = field(default_factory=list)
    last_interaction: float = 0.0
    interaction_count: int = 0
    extra: dict = field(default_factory=dict)


class UserProfileStore:
    """用户画像存储管理"""

    def __init__(self, path: str = USER_PROFILE_PATH):
        self.path = path
        self._lock = Lock()
        self._save_lock = Lock()
        self._profiles: dict[str, UserProfile] = {}
        self._load()
        logger.info("UserProfileStore initialized")

    def _load(self):
        """从文件加载画像数据
        
        注意: 单条 profile 解析失败不会阻止其余 profile 的加载。
        已成功加载的 profile 会保留在 _profiles 中，即使后续条目出错。
        这是有意为之的行为——确保部分损坏的文件不会导致全部数据丢失。
        """
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    logger.error(f"User profiles file is not a JSON object (got {type(data).__name__}), keeping existing profiles")
                    return
                allowed_keys = {f.name for f in fields(UserProfile)}
                for uid, profile_data in data.items():
                    if not isinstance(profile_data, dict):
                        logger.warning(f"Skipping non-dict profile '{uid}'")
                        continue
                    try:
                        sanitized = {k: v for k, v in profile_data.items() if k in allowed_keys}
                        sanitized['user_id'] = uid
                        self._profiles[uid] = UserProfile(**sanitized)
                    except (TypeError, ValueError) as e:
                        logger.warning(f"Skipping malformed profile '{uid}': {e}")
            except Exception as e:
                logger.error(f"Failed to load user profiles: {e}")
        else:
            dir_path = os.path.dirname(self.path) or '.'
            os.makedirs(dir_path, exist_ok=True)

    def _build_snapshot_unlocked(self) -> dict[str, dict]:
        return {uid: asdict(profile) for uid, profile in self._profiles.items()}

    def _save(self, snapshot: dict[str, dict]):
        """保存画像数据到文件（原子写入）"""
        fd = None
        tmp_path = None
        try:
            dir_path = os.path.dirname(self.path) or '.'
            os.makedirs(dir_path, exist_ok=True)
            data = snapshot
            fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix='.tmp')
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                fd = None  # os.fdopen takes ownership
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.path)
            tmp_path = None
        except Exception as e:
            logger.error(f"Failed to save user profiles: {e}")
        finally:
            if fd is not None:
                os.close(fd)
            if tmp_path is not None:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    def _get_profile_unlocked(self, user_id: str) -> UserProfile:
        """获取用户画像（调用方须已持有 _lock），不存在则创建"""
        if user_id not in self._profiles:
            self._profiles[user_id] = UserProfile(user_id=user_id)
        return self._profiles[user_id]

    def get_profile(self, user_id: str) -> UserProfile:
        """获取用户画像的快照副本（线程安全，调用方不能修改内部状态）"""
        with self._lock:
            profile = self._get_profile_unlocked(user_id)
            return copy.deepcopy(profile)

    def update_profile(self, user_id: str, **kwargs) -> UserProfile:
        """更新用户画像字段（user_id 字段不可修改）"""
        allowed = {f.name for f in fields(UserProfile)} - {'user_id'}
        with self._lock:
            profile = self._get_profile_unlocked(user_id)
            for key, value in kwargs.items():
                if key in allowed:
                    setattr(profile, key, value)
            profile.last_interaction = time.time()
            profile_snapshot = copy.deepcopy(profile)
            snapshot = self._build_snapshot_unlocked()
            with self._save_lock:
                self._save(snapshot)
        return profile_snapshot

    def add_trait(self, user_id: str, trait: str):
        """添加用户特征标签"""
        with self._lock:
            profile = self._get_profile_unlocked(user_id)
            if trait not in profile.traits:
                profile.traits.append(trait)
                snapshot = self._build_snapshot_unlocked()
                with self._save_lock:
                    self._save(snapshot)

    def remove_trait(self, user_id: str, trait: str):
        """移除用户特征标签"""
        with self._lock:
            profile = self._get_profile_unlocked(user_id)
            if trait in profile.traits:
                profile.traits.remove(trait)
                snapshot = self._build_snapshot_unlocked()
                with self._save_lock:
                    self._save(snapshot)

    def add_fact(self, user_id: str, fact: str):
        """添加确定性事实"""
        with self._lock:
            profile = self._get_profile_unlocked(user_id)
            if fact not in profile.facts:
                profile.facts.append(fact)
                snapshot = self._build_snapshot_unlocked()
                with self._save_lock:
                    self._save(snapshot)

    def update_fact(self, user_id: str, old_fact: str, new_fact: str):
        """更新事实"""
        with self._lock:
            profile = self._get_profile_unlocked(user_id)
            for i, f in enumerate(profile.facts):
                if f == old_fact:
                    profile.facts[i] = new_fact
                    snapshot = self._build_snapshot_unlocked()
                    with self._save_lock:
                        self._save(snapshot)
                    break

    def remove_fact(self, user_id: str, fact: str):
        """移除事实"""
        with self._lock:
            profile = self._get_profile_unlocked(user_id)
            if fact in profile.facts:
                profile.facts.remove(fact)
                snapshot = self._build_snapshot_unlocked()
                with self._save_lock:
                    self._save(snapshot)

    def set_relationship(self, user_id: str, target: str, relation: str):
        """设置关系"""
        with self._lock:
            profile = self._get_profile_unlocked(user_id)
            profile.relationships[target] = relation
            snapshot = self._build_snapshot_unlocked()
            with self._save_lock:
                self._save(snapshot)

    def increment_interaction(self, user_id: str):
        """增加交互计数"""
        with self._lock:
            profile = self._get_profile_unlocked(user_id)
            profile.interaction_count += 1
            profile.last_interaction = time.time()
            snapshot = self._build_snapshot_unlocked()
            with self._save_lock:
                self._save(snapshot)

    def increment_and_update_profile(self, user_id: str, **kwargs):
        """原子地增加交互计数并更新其他字段（单次 _save）"""
        allowed = {f.name for f in fields(UserProfile)} - {'user_id'}
        with self._lock:
            profile = self._get_profile_unlocked(user_id)
            profile.interaction_count += 1
            profile.last_interaction = time.time()
            for key, value in kwargs.items():
                if key in allowed:
                    setattr(profile, key, value)
            snapshot = self._build_snapshot_unlocked()
            with self._save_lock:
                self._save(snapshot)

    def get_profile_prompt(self, user_id: str) -> str:
        """将用户画像格式化为 prompt 文本"""
        with self._lock:
            profile = self._get_profile_unlocked(user_id)
            # 在锁内快照所有可变字段，避免释放锁后读取发生竞态
            name = profile.name
            nickname = profile.nickname
            platform = profile.platform
            traits = list(profile.traits)
            preferences = dict(profile.preferences)
            relationships = dict(profile.relationships)
            facts = list(profile.facts)
            interaction_count = profile.interaction_count

        parts = []
        if name:
            parts.append(f"名字: {name}")
        if nickname:
            parts.append(f"昵称: {nickname}")
        if platform:
            parts.append(f"平台: {platform}")
        if traits:
            parts.append(f"特征: {', '.join(traits)}")
        if preferences:
            prefs = ', '.join(f"{k}: {v}" for k, v in preferences.items())
            parts.append(f"偏好: {prefs}")
        if relationships:
            rels = ', '.join(f"{k}: {v}" for k, v in relationships.items())
            parts.append(f"关系: {rels}")
        if facts:
            facts_str = '\n  '.join(f"- {f}" for f in facts)
            parts.append(f"已知事实:\n  {facts_str}")
        if interaction_count:
            parts.append(f"互动次数: {interaction_count}")
        return '\n'.join(parts) if parts else "暂无画像信息"

    def get_all_profiles(self) -> dict[str, UserProfile]:
        """获取所有用户画像（线程安全深拷贝快照）"""
        with self._lock:
            return copy.deepcopy(self._profiles)

    def delete_profile(self, user_id: str) -> bool:
        """删除用户画像"""
        with self._lock:
            if user_id in self._profiles:
                del self._profiles[user_id]
                snapshot = self._build_snapshot_unlocked()
                with self._save_lock:
                    self._save(snapshot)
            else:
                return False
        return True
