import asyncio
import os
import inspect

from typing import Optional, Union, Any, Callable
from copy import deepcopy

from core.logging_manager import get_logger
from core.utils.path_utils import get_data_path
from core.db.service import DatabaseService

logger = get_logger("sticker", "orange")


class StickerManager:
    def __init__(self, db: DatabaseService):
        self.db = db
        self.sticker_folder = f"{get_data_path()}/sticker"
        self._sticker_cache: dict = {}
        self._sticker_paths: list = []
        self._sticker_index: int = 0
        self._on_registered_callbacks: list[Callable] = []

    async def init(self):
        """Load stickers from database into memory cache."""
        os.makedirs(self.sticker_folder, exist_ok=True)
        await self._load_from_db()

    def on_sticker_registered(self, callback: Callable):
        self._on_registered_callbacks.append(callback)

    def off_sticker_registered(self, callback: Callable):
        try:
            self._on_registered_callbacks.remove(callback)
        except ValueError:
            pass

    async def _fire_registered(self, sid: str, info: dict):
        for cb in self._on_registered_callbacks:
            try:
                if inspect.iscoroutinefunction(cb):
                    await cb(sid, info)
                else:
                    cb(sid, info)
            except Exception as e:
                logger.error(f"Sticker registered callback error: {e}")

    async def _load_from_db(self):
        try:
            rows = await self.db.list_stickers()
            # Sort by numeric id so stickers display in creation order
            def _sort_key(row):
                sid = row["id"]
                try:
                    return (0, int(sid))
                except ValueError:
                    return (1, sid)
            rows.sort(key=_sort_key)

            self._sticker_cache = {}
            self._sticker_paths = []
            numeric_ids = []
            for row in rows:
                sid = row["id"]
                self._sticker_cache[sid] = {
                    "desc": row["desc"],
                    "path": row["path"],
                    "extra": row.get("extra") or {},
                }
                self._sticker_paths.append(row["path"])
                if sid.isdigit():
                    numeric_ids.append(int(sid))
            self._sticker_index = max(numeric_ids) if numeric_ids else 0
        except Exception as e:
            logger.error(f"Error loading stickers from database: {e}")
            self._sticker_cache = {}
            self._sticker_paths = []

    @property
    def sticker_dict(self) -> dict:
        return self._sticker_cache

    @property
    def sticker_paths(self) -> list:
        return self._sticker_paths

    async def register_sticker(self, filename: str, desc: str, sticker_id: Optional[str] = None):
        if sticker_id:
            sid = str(sticker_id)
        else:
            self._sticker_index += 1
            sid = str(self._sticker_index)

        await self.db.add_sticker(sid, desc, filename, extra={})

        self._sticker_cache[sid] = {"desc": desc, "path": filename, "extra": {}}
        self._sticker_paths.append(filename)

        asyncio.create_task(self._fire_registered(sid, {"desc": desc, "path": filename}))

    async def update_sticker_desc(self, sticker_id: str, desc: str):
        sid = str(sticker_id)
        sticker = self._sticker_cache.get(sid)
        if not sticker:
            raise KeyError(sid)
        await self.db.update_sticker(sid, desc=desc)
        sticker["desc"] = desc
        return {
            "id": sid,
            "desc": sticker.get("desc") or "",
            "path": sticker.get("path") or "",
        }

    async def delete_sticker(self, sticker_id: str, delete_file: bool = False):
        sid = str(sticker_id)
        sticker = self._sticker_cache.pop(sid, None)
        if not sticker:
            raise KeyError(sid)
        path = sticker.get("path")
        if path:
            self._sticker_paths = [p for p in self._sticker_paths if p != path]
            file_path = os.path.join(self.sticker_folder, path)
            if delete_file and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception as e:
                    logger.error(f"Error deleting sticker file {file_path}: {e}")
        await self.db.delete_sticker(sid)

    def set_sticker_extra(self, sticker_id: str, key: Union[int, str], value: Any):
        sticker_info_dict = self._sticker_cache.get(sticker_id)
        if sticker_info_dict:
            if key is None:
                return False
            sticker_info_dict.setdefault("extra", {})[key] = value
            return True
        return False

    def get_sticker_extra(self, sticker_id: str, key: Optional[Union[int, str]] = None):
        sticker_info_dict = self._sticker_cache.get(sticker_id)
        if sticker_info_dict is None:
            raise KeyError(sticker_id)

        if key is None:
            return deepcopy(sticker_info_dict.get("extra", {}))

        value = sticker_info_dict.get("extra", {}).get(key)
        return deepcopy(value)

    async def add_sticker(self, file_bytes: bytes, original_filename: str, sticker_id: str | None = None, desc: str | None = None):
        if not original_filename:
            raise ValueError("File name is required")
        base_name = os.path.basename(original_filename)
        try:
            _, ext = os.path.splitext(base_name)
        except Exception:
            ext = ""
        if not ext:
            ext = ".png"
            base_name = base_name + ext
        filename = base_name
        os.makedirs(self.sticker_folder, exist_ok=True)
        file_path = os.path.join(self.sticker_folder, filename)
        with open(file_path, "wb") as f:
            f.write(file_bytes)
        final_desc = desc or ""
        if sticker_id and str(sticker_id).strip():
            sid = str(sticker_id).strip()
            if sid in self._sticker_cache:
                raise ValueError(f"Sticker id {sid} already exists")
            if sid.isdigit():
                try:
                    numeric_id = int(sid)
                    if numeric_id > self._sticker_index:
                        self._sticker_index = numeric_id
                except Exception:
                    pass
        else:
            self._sticker_index += 1
            sid = str(self._sticker_index)
        await self.register_sticker(filename, final_desc, sid)
        return {
            "id": sid,
            "desc": final_desc,
            "path": filename,
        }
